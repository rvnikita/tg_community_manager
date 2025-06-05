import requests
import os

import src.helpers.logging_helper as logging_helper

logger = logging_helper.get_logger()

def check_health():
    url = "http://localhost:8081/healthz"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200 and resp.text == "OK":
            logger.info("Bot is healthy")
            return True
        logger.error(f"Unexpected health check response: {resp.status_code} {resp.text!r}")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
    return False

def restart_heroku():
    url = f"https://api.heroku.com/apps/{os.getenv('HEROKU_APP_NAME')}/dynos"
    headers = {
        "Accept": "application/vnd.heroku+json; version=3",
        "Authorization": f"Bearer {os.getenv('HEROKU_API_KEY')}"
    }
    resp = requests.delete(url, headers=headers)
    if resp.status_code == 202:
        logger.info("Heroku dynos restarted")
    else:
        logger.error(f"Failed to restart Heroku ({resp.status_code}): {resp.text}")

if __name__ == "__main__":
    if not check_health():
        restart_heroku()
