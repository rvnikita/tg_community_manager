import src.db_helper as db_helper
import src.user_helper as user_helper
import src.logging_helper as logging
import src.config_helper as config_helper

from telegram import Bot
from telegram.request import HTTPXRequest

logger = logging.get_logger()

config = config_helper.get_config()

bot = Bot(config['BOT']['KEY'],
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)

async def change_rating(user_id, judge_id, chat_id, change_value, message_id = None, announce = True):
    with db_helper.session_scope() as db_session:
        user_status = db_session.query(db_helper.User_Status).filter(
            db_helper.User_Status.chat_id == chat_id,
            db_helper.User_Status.user_id == user_id).first()
        if user_status is None:
            user_status = db_helper.User_Status(chat_id=chat_id, user_id=user_id, rating=0)
            db_session.add(user_status)
            db_session.commit()

        judge_status = db_session.query(db_helper.User_Status).filter(
            db_helper.User_Status.chat_id == chat_id,
            db_helper.User_Status.user_id == judge_id).first()
        if judge_status is None:
            judge_status = db_helper.User_Status(chat_id=chat_id, user_id=judge_id, rating=0)
            db_session.add(judge_status)
            db_session.commit()

        user_status.rating += change_value

        if change_value >= 1:
            rating_action = "increased"

        elif change_value <= -1:
            rating_action = "decreased"
        else:
            rating_action = "not changed"
            pass

        db_session.commit()

        user_mention = user_helper.get_user_mention(user_id)
        judge_mention = user_helper.get_user_mention(judge_id)

        text_to_send = f"{judge_mention} ({int(judge_status.rating)}) {rating_action} reputation of {user_mention} ({user_status.rating})"

        if announce == True:
            if message_id is None:
                await bot.send_message(chat_id=chat_id, text=text_to_send)
            else:
                await bot.send_message(chat_id=chat_id, text=text_to_send, reply_to_message_id=message_id)

        logger.info(text_to_send + f" in chat {chat_id} ")

