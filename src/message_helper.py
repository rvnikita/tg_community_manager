import datetime
import traceback
from sqlalchemy.dialects.postgresql import insert

import src.db_helper as db_helper
import src.logging_helper as logging

logger = logging.get_logger()

# TODO: add non required parameter "spam prediction probability" that would be used when we we log with spam detection part of the code. That will easier to filter and manually verify in batch. Not going to use it in the prediction itself.
async def log_or_update_message(user_id, user_nickname, user_current_rating, chat_id, message_content, action_type, reporting_id, reporting_id_nickname, reason_for_action, message_id, is_spam=False, manually_verified=False, embedding=None, forwarded_message_id=None, forwarded_chat_id=None, forwarded_message_content=None):
    try:
        # logger.info("Processing message log")

        with db_helper.session_scope() as db_session:
            # Define the insert statement with potential conflict
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
                forwarded_message_id=forwarded_message_id,  # New field for forwarded message ID
                forwarded_chat_id=forwarded_chat_id,  # New field for forwarded chat ID
                forwarded_message_content=forwarded_message_content  # New field for forwarded message content
            )

            # Define the on_conflict clause
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
                    'forwarded_message_id': forwarded_message_id,  # Update on conflict
                    'forwarded_chat_id': forwarded_chat_id,  # Update on conflict
                    'forwarded_message_content': forwarded_message_content  # Update on conflict
                }
            )

            # Execute the upsert operation
            db_session.execute(on_conflict_stmt)
            db_session.commit()
            # logger.info(f"Message {message_id} processed successfully for chat {chat_id}.")
            return True
    except Exception as e:
        logger.error(f"Error processing message log: {e}. Traceback: {traceback.format_exc()}")
        return False
