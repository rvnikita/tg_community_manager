from admin_log import admin_log
import os
import configparser
from telegram import ForceReply, Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from datetime import datetime, timezone
import psycopg2

admin_log(f"Starting {__file__} in {os.environ['MODE']} mode at {os.uname()}")

chat_id = os.environ['CHAT_ID']
bot_key = os.environ['BOT_KEY']
bot_nickname = os.environ['BOT_NICKNAME']

config = configparser.ConfigParser()
config.read('config/bot.ini')

bot = Bot(bot_key)

########################


async def tg_new_member(update, context):
    
    delete_NEW_CHAT_MEMBERS_message = config.getboolean('NEW_CHAT_MEMBERS', 'delete_NEW_CHAT_MEMBERS_message')
    
    if delete_NEW_CHAT_MEMBERS_message == True:
        await bot.delete_message(update.message.chat.id,update.message.id)
    
async def tg_text(update, context):
    return

def main() -> None:
    application = Application.builder().token(bot_key).build()
    
    application.add_handler(MessageHandler(filters.TEXT, tg_text))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_new_member))

    # Start the Bot
    application.run_polling()
        

if __name__ == '__main__':
    main()