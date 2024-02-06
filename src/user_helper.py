import src.db_helper as db_helper
import src.logging_helper as logging

from sqlalchemy.dialects.postgresql import insert
import traceback

logger = logging.get_logger()

def get_user_mention(user_id: int) -> str:
    with db_helper.session_scope() as db_session:

        user = db_session.query(db_helper.User).filter_by(id=user_id).first()

        if user is None:
            return str(user_id)
        else:
            # This lines was written by GPT-4 to generate desirable output for different user input combinations:
            # Output table for different user input combinations:
            #   First name | Last name | Username   | ID   | `user_mention`
            # --------------|-----------|------------|------|------------------------------
            #   "Nikita"    | "Rvachev" | "rvnikita" | 123  | "Nikita Rvachev - @rvnikita"
            #   "Nikita"    | "Rvachev" | None       | 123  | "Nikita Rvachev"
            #   None        | None      | "rvnikita" | 123  | "@rvnikita"
            #   "Nikita"    | None      | "rvnikita" | 123  | "Nikita - @rvnikita"
            #   None        | "Rvachev" | "rvnikita" | 123  | "Rvachev - @rvnikita"
            #   "Nikita"    | None      | None       | 123  | "Nikita"
            #   None        | "Rvachev" | None       | 123  | "Rvachev"
            #   None        | None      | None       | 123  | "123"
            return ', '.join(filter(bool, [
                f"{user.first_name} {user.last_name} - @{user.username}" if user.first_name and user.last_name and user.username else f"{user.first_name} {user.last_name}" if user.first_name and user.last_name else f"@{user.username}" if user.username else str(
                    user.id)]))

def db_upsert_user(user_id, chat_id, username, last_message_datetime, first_name=None, last_name=None):
    try:
        with db_helper.session_scope() as db_session:
            # Upsert User
            insert_stmt = insert(db_helper.User).values(
                id=user_id, username=username, first_name=first_name, last_name=last_name
            ).on_conflict_do_update(
                index_elements=['id'],  # Assumes 'id' is a unique index or primary key
                set_=dict(username=username, first_name=first_name, last_name=last_name)
            )
            db_session.execute(insert_stmt)

            # Upsert User Status
            insert_stmt = insert(db_helper.User_Status).values(
                user_id=user_id, chat_id=chat_id, last_message_datetime=last_message_datetime
            ).on_conflict_do_update(
                index_elements=['user_id', 'chat_id'],  # Assumes this combination is unique
                set_=dict(last_message_datetime=last_message_datetime)
            )
            db_session.execute(insert_stmt)

            db_session.commit()
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")