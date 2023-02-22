import os
import configparser
import requests


config = configparser.ConfigParser()
config.read('config/settings.ini')
config.read('config/bot.ini')

def admin_log(text):

    # print(os.environ['BOT_KEY'])
    URL = f"https://api.telegram.org/bot{config['BOT']['KEY']}/sendMessage?chat_id={config['BOT']['ADMIN_ID']}&text={text}"
    r = requests.get(url = URL)
    data = r.json()