import os
import logging
import urllib.parse
import requests

import sentry_sdk

LOGGING_FORMAT = os.getenv("ENV_LOGGING_FORMAT", "%(asctime)s - %(levelname)s - %(message)s")
LOGGING_LEVEL = os.getenv("ENV_LOGGING_LEVEL", "INFO").upper()
ENABLE_TELEGRAM = os.getenv("LOG_TO_TELEGRAM", "false").lower() == "true"
ENABLE_SENTRY   = os.getenv("LOG_TO_SENTRY",   "false").lower() == "true"

class TelegramLoggerHandler(logging.Handler):
    def __init__(self, chat_id):
        super().__init__()
        self.chat_id = chat_id

    def emit(self, record):
        try:
            text = urllib.parse.quote(self.format(record), safe="")
            url = (
                f"https://api.telegram.org/bot{os.getenv('ENV_BOT_KEY')}"
                f"/sendMessage?chat_id={self.chat_id}"
                f"&text={text}&disable_web_page_preview=true"
            )
            resp = requests.get(url, timeout=5)
            if resp.status_code == 429:
                # rate‐limit hit
                print(f"TelegramLoggerHandler rate‐limited: {resp.text}")
            elif resp.status_code != 200:
                print(f"TelegramLoggerHandler failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            # avoid infinite recursion
            print(f"TelegramLoggerHandler.emit exception: {e}")
            self.handleError(record)

def get_logger():
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOGGING_LEVEL, logging.INFO))

    # clear existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    fmt = logging.Formatter(LOGGING_FORMAT)

    # 1) console
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 2) telegram
    if ENABLE_TELEGRAM:
        info_id  = os.getenv("ENV_INFO_CHAT_ID")
        error_id = os.getenv("ENV_ERROR_CHAT_ID")

        if info_id:
            h = TelegramLoggerHandler(info_id)
            h.setLevel(logging.INFO)
            h.setFormatter(fmt)
            logger.addHandler(h)

        if error_id:
            h = TelegramLoggerHandler(error_id)
            h.setLevel(logging.ERROR)
            h.setFormatter(fmt)
            logger.addHandler(h)

    # 3) sentry
    if ENABLE_SENTRY and os.getenv("SENTRY_DSN"):
        sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=1.0)

    # quiet down httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return logger
