import datetime
import traceback
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func

import src.db_helper as db_helper
import src.logging_helper as logging

logger = logging.get_logger()

# TODO: add non required parameter "spam prediction probability" that would be used when we we log with spam detection part of the code. That will easier to filter and manually verify in batch. Not going to use it in the prediction itself.
import datetime
import traceback
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func
import src.db_helper as db_helper
import src.logging_helper as logging

logger = logging.get_logger()

import datetime, traceback
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func
import src.db_helper as db_helper
import src.logging_helper as logging

logger = logging.get_logger()

import datetime
import traceback
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func
import src.db_helper as db_helper
import src.logging_helper as logging

logger = logging.get_logger()

def log_or_update_message(
    chat_id,                 # mandatory
    message_id,              # mandatory
    user_id=None,
    user_nickname=None,
    user_current_rating=None,
    message_content=None,
    action_type=None,
    reporting_id=None,
    reporting_id_nickname=None,
    reason_for_action=None,
    is_spam=None,
    manually_verified=None,
    embedding=None,
    is_forwarded=None,
    reply_to_message_id=None,
    spam_prediction_probability=None
):
    try:
        # Convert spam_prediction_probability to float if provided.
        if spam_prediction_probability is not None:
            try:
                spam_prediction_probability = float(spam_prediction_probability)
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid spam_prediction_probability value: {spam_prediction_probability}. Error: {e}")
                spam_prediction_probability = None
        with db_helper.session_scope() as db_session:
            insert_stmt = insert(db_helper.Message_Log).values(
                message_id=message_id,
                chat_id=chat_id,
                message_content=message_content,
                user_id=user_id,
                user_nickname=user_nickname,
                user_current_rating=user_current_rating,
                message_timestamp=datetime.datetime.now(),
                is_spam=is_spam,
                action_type=action_type,
                reporting_id=reporting_id,
                reporting_id_nickname=reporting_id_nickname,
                reason_for_action=reason_for_action,
                created_at=datetime.datetime.now(),
                embedding=embedding,
                manually_verified=manually_verified,
                is_forwarded=is_forwarded,
                reply_to_message_id=reply_to_message_id,
                spam_prediction_probability=spam_prediction_probability
            ).returning(db_helper.Message_Log.id)
            on_conflict_stmt = insert_stmt.on_conflict_do_update(
                index_elements=['message_id', 'chat_id'],
                set_={
                    'message_content': func.coalesce(insert_stmt.excluded.message_content, db_helper.Message_Log.message_content),
                    'user_id': func.coalesce(insert_stmt.excluded.user_id, db_helper.Message_Log.user_id),
                    'user_nickname': func.coalesce(insert_stmt.excluded.user_nickname, db_helper.Message_Log.user_nickname),
                    'user_current_rating': func.coalesce(insert_stmt.excluded.user_current_rating, db_helper.Message_Log.user_current_rating),
                    'is_spam': func.coalesce(insert_stmt.excluded.is_spam, db_helper.Message_Log.is_spam),
                    'action_type': func.coalesce(insert_stmt.excluded.action_type, db_helper.Message_Log.action_type),
                    'reporting_id': func.coalesce(insert_stmt.excluded.reporting_id, db_helper.Message_Log.reporting_id),
                    'reporting_id_nickname': func.coalesce(insert_stmt.excluded.reporting_id_nickname, db_helper.Message_Log.reporting_id_nickname),
                    'reason_for_action': func.coalesce(insert_stmt.excluded.reason_for_action, db_helper.Message_Log.reason_for_action),
                    'manually_verified': func.coalesce(insert_stmt.excluded.manually_verified, db_helper.Message_Log.manually_verified),
                    'is_forwarded': func.coalesce(insert_stmt.excluded.is_forwarded, db_helper.Message_Log.is_forwarded),
                    'reply_to_message_id': func.coalesce(insert_stmt.excluded.reply_to_message_id, db_helper.Message_Log.reply_to_message_id),
                    'spam_prediction_probability': func.coalesce(insert_stmt.excluded.spam_prediction_probability, db_helper.Message_Log.spam_prediction_probability),
                    'embedding': func.coalesce(insert_stmt.excluded.embedding, db_helper.Message_Log.embedding)
                }
            ).returning(db_helper.Message_Log.id)
            result = db_session.execute(on_conflict_stmt)
            db_session.commit()
            row = result.fetchone()
            if row:
                return row[0]
            else:
                logger.warning(f"No rows were affected for message_id {message_id} in chat_id {chat_id}.")
                return None
    except Exception as e:
        logger.error(f"Error processing message log: {e}. Traceback: {traceback.format_exc()}")
        return None

