import datetime
import traceback
from sqlalchemy.dialects.postgresql import insert

import src.db_helper as db_helper
import src.logging_helper as logging

logger = logging.get_logger()

# TODO: add non required parameter "spam prediction probability" that would be used when we we log with spam detection part of the code. That will easier to filter and manually verify in batch. Not going to use it in the prediction itself.
def log_or_update_message(
    user_id, user_nickname, user_current_rating, chat_id, message_content, action_type, 
    reporting_id, reporting_id_nickname, reason_for_action, message_id, is_spam=False, 
    manually_verified=False, embedding=None, is_forwarded=None, reply_to_message_id=None, spam_prediction_probability=None):
    
    try:
        with db_helper.session_scope() as db_session:
            # Prepare the insert statement with RETURNING clause
            insert_stmt = insert(db_helper.Message_Log).values(
                message_id=message_id,
                message_content=message_content,
                user_id=user_id,
                user_nickname=user_nickname,
                user_current_rating=user_current_rating,
                chat_id=chat_id,
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
            ).returning(db_helper.Message_Log.id)  # Return the ID of the row

            # Handle conflicts on 'message_id' and 'chat_id'
            on_conflict_stmt = insert_stmt.on_conflict_do_update(
                index_elements=['message_id', 'chat_id'],
                set_={
                    'is_spam': is_spam,
                    'action_type': action_type,
                    'reporting_id': reporting_id,
                    'reporting_id_nickname': reporting_id_nickname,
                    'reason_for_action': reason_for_action,
                    'message_timestamp': datetime.datetime.now(),
                    'manually_verified': manually_verified,
                    'is_forwarded': is_forwarded,
                    'reply_to_message_id': reply_to_message_id,
                    'spam_prediction_probability': spam_prediction_probability
                }
            ).returning(db_helper.Message_Log.id)  # Also return the ID on conflict

            # Execute the statement and fetch the ID
            result = db_session.execute(on_conflict_stmt)
            db_session.commit()

            row_id = result.fetchone()[0]  # Fetch the ID from the result
            return row_id

    except Exception as e:
        logger.error(f"Error processing message log: {e}. Traceback: {traceback.format_exc()}")
        return None
