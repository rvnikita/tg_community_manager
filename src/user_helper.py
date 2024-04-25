from sqlalchemy.dialects.postgresql import insert
import traceback

import src.db_helper as db_helper
import src.logging_helper as logging
import src.cache_helper as cache_helper
import src.rating_helper as rating_helper

logger = logging.get_logger()

def get_user_id(username: str = None):
    try:
        with db_helper.session_scope() as db_session:
            if username:
                username = username.lstrip('@')
                user = db_session.query(db_helper.User).filter_by(username=username).first()
                if user:
                    return user.id
            return None
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")


def get_user_mention(user_id: int, chat_id: int = None) -> str:
    try:
        with db_helper.session_scope() as db_session:
            user = db_session.query(db_helper.User).filter_by(id=user_id).first()
            if user is None:
                # If the user is not found, return the user ID as a string.
                return str(user_id)
            else:
                # This part constructs the user mention string based on the available user information.
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
                parts = [user.first_name, user.last_name]  # Start with possible first and last name
                full_name = ' '.join(filter(None, parts))  # Combine them with a space, filter out None values
                if full_name and user.username:
                    user_mention = f"{full_name} - @{user.username}"
                elif user.username:
                    user_mention = f"@{user.username}"
                elif full_name:
                    user_mention = full_name
                else:
                    user_mention = str(user.id)

                # If chat_id is provided, attempt to fetch and append the user's total rating
                if chat_id is not None:
                    user_total_rating = rating_helper.get_rating(user_id, chat_id)
                    if user_total_rating is not None:
                        # Append the total rating to the user mention string if available.
                        user_mention += f" ({user_total_rating})"

            return user_mention

    except Exception as e:
        # Log the error and return the user_id as the mention in case of an error.
        logger.error(f"Error generating mention for user_id {user_id}: {traceback.format_exc()}")
        return str(user_id)


def db_upsert_user(user_id, chat_id, username, last_message_datetime, first_name=None, last_name=None):
    try:
        # Generate a unique cache key for the user's data
        cache_key = f"user_{user_id}_chat_{chat_id}"

        # Attempt to retrieve the user's current data from cache
        cached_data = cache_helper.get_key(cache_key)

        # Define the new data for comparison and potential cache update
        new_data = {"username": username, "first_name": first_name, "last_name": last_name, "last_message_datetime": last_message_datetime, }

        # If data is in cache and hasn't changed, skip DB operation
        if cached_data and cached_data == new_data:
            return  # Data is up-to-date; no need to hit the DB

        else:
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

                # Update the cache with the new data
                cache_helper.set_key(cache_key, new_data, expire=3600)  # Cache expires in 1 hour (3600 seconds)
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")