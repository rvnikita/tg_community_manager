import os
import configparser
import requests


config = configparser.ConfigParser()
config_path = os.path.dirname(__file__) + '/../config/' #we need this trick to get path to config folder
print(config_path)
config.read(config_path + 'settings.ini')
config.read(config_path + 'bot.ini')

def admin_log(text, critical = False):
    if critical == True:
        URL = f"https://api.telegram.org/bot{config['BOT']['KEY']}/sendMessage?chat_id={config['BOT']['ADMIN_ID']}&text={text}"
    else:
        URL = f"https://api.telegram.org/bot{config['BOT']['LOGS_KEY']}/sendMessage?chat_id={config['BOT']['ADMIN_ID']}&text={text}"
    r = requests.get(url = URL)
    data = r.json()