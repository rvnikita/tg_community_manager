from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from pgvector.sqlalchemy import Vector


import src.helpers.db_helper as db_helper
import src.helpers.logging_helper as logging_helper

logger = logging_helper.get_logger()

def find_best_embeddings_trigger(chat_id, embedding, threshold=0.3):
    embedding_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
    with db_helper.session_scope() as session:
        sql = f"""
            SELECT id, content_id, embedding <=> '{embedding_str}'::vector as distance
            FROM tg_embeddings_auto_reply_trigger
            WHERE chat_id = :chat_id
              AND embedding <=> '{embedding_str}'::vector <= :threshold
            ORDER BY distance ASC
            LIMIT 1
        """
        row = session.execute(
            text(sql),
            {"chat_id": chat_id, "threshold": threshold}
        ).fetchone()
        if row:
            logger.info(f"🥶 Found embeddings row: {row}, distance: {row.distance}")
            return dict(row._mapping)
        return None

        
def get_content_by_id(content_id):
    with db_helper.session_scope() as session:
        obj = session.query(db_helper.Embeddings_Auto_Reply_Content).filter_by(id=content_id).one_or_none()
        if obj is None:
            return None
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}

def can_send_reply(content, now=None):
    now = now or datetime.now(timezone.utc)
    if content["last_reply_time"] and content["reply_delay"]:
        next_reply_time = content["last_reply_time"] + timedelta(seconds=content["reply_delay"])
        return now >= next_reply_time
    return True

def update_reply_usage(content_id, now=None):
    now = now or datetime.now(timezone.utc)
    with db_helper.session_scope() as session:
        content = session.query(db_helper.Embeddings_Auto_Reply_Content).filter_by(id=content_id).one_or_none()
        if not content:
            logger.warning(f"Embeddings_Auto_Reply_Content id={content_id} not found for update.")
            return False
        content.last_reply_time = now
        content.usage_count = (content.usage_count or 0) + 1
        session.commit()
        return True

async def send_embeddings_reply(bot, chat_id, reply_text, reply_to_message_id, content_obj, now=None):
    now = now or datetime.now(timezone.utc)
    if not can_send_reply(content_obj, now):
        logger.info(f"Reply suppressed for content_id={content_obj['id']} in chat_id={chat_id} due to reply_delay.")
        return False

    await bot.send_message(
        chat_id=chat_id,
        text=reply_text,
        reply_to_message_id=reply_to_message_id
    )

    update_reply_usage(content_obj["id"], now)
    logger.info(f"Auto-reply sent for content_id={content_obj['id']} in chat_id={chat_id}")
    return True
