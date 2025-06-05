import requests
import os

import src.helpers.logging_helper as logging_helper

logger = logging_helper.get_logger()

def check_health():
    app_name = os.getenv("HEROKU_APP_NAME")
    if not app_name:
        logger.error("HEROKU_APP_NAME is not set in environment")
        return False
    url = f"https://{app_name}.herokuapp.com/healthz"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200 and resp.text.strip() == "OK":
            logger.info("Bot is healthy")
            return True
        logger.error(f"Unexpected health check response: {resp.status_code} {resp.text!r}")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
    return False

def restart_heroku():
    app_name = os.getenv("HEROKU_APP_NAME")
    if not app_name:
        logger.error("HEROKU_APP_NAME is not set in environment")
        return
    url = f"https://api.heroku.com/apps/{app_name}/dynos"
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
