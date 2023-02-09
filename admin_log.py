import os

def admin_log(text):
    admin_id = 88834504
    import requests
    print(os.environ['BOT_KEY'])
    URL = f"https://api.telegram.org/bot{os.environ['BOT_KEY']}/sendMessage?chat_id={admin_id}&text={text}"
    r = requests.get(url = URL)
    data = r.json()