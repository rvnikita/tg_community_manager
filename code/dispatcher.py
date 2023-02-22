from admin_log import admin_log
import os
import configparser
from telegram import Bot
from telegram.ext import Application, MessageHandler, filters

config = configparser.ConfigParser()
config.read('config/settings.ini')
config.read('config/bot.ini')
config.read('config/db.ini')

admin_log(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = Bot(config['BOT']['KEY'])

########################


async def tg_new_member(update, context):
    
    delete_NEW_CHAT_MEMBERS_message = config.getboolean('NEW_CHAT_MEMBERS', 'delete_NEW_CHAT_MEMBERS_message')
    
    if delete_NEW_CHAT_MEMBERS_message == True:
        await bot.delete_message(update.message.chat.id,update.message.id)
        admin_log(f"Deleted {update.message.id} message from {update.message.chat.id} chat ")

    
async def tg_text(update, context):
    return

def main() -> None:
    application = Application.builder().token(config['BOT']['KEY']).build()
    
    application.add_handler(MessageHandler(filters.TEXT, tg_text))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_new_member))

    # Start the Bot
    application.run_polling()
        

if __name__ == '__main__':
    main()