import src.config_helper as config_helper

import requests

config = config_helper.get_config()

def admin_log(text, critical = False):
    if critical == True:
        URL = f"https://api.telegram.org/bot{config['BOT']['KEY']}/sendMessage?chat_id={config['BOT']['ADMIN_ID']}&text={text}"
    else:
        URL = f"https://api.telegram.org/bot{config['BOT']['LOGS_KEY']}/sendMessage?chat_id={config['BOT']['ADMIN_ID']}&text={text}"
    r = requests.get(url = URL)
    data = r.json()