from sqlalchemy.dialects.postgresql import insert
import traceback
from datetime import datetime, timezone

import src.db_helper as db_helper
import src.logging_helper as logging
import src.cache_helper as cache_helper
import src.rating_helper as rating_helper


logger = logging.get_logger()

def get_user_id(username: str):
    with db_helper.session_scope() as session:
        u = session.query(db_helper.User).filter_by(username=username).first()
        return u.id if u else None

def get_user_mention(user_id: int, chat_id: int | None = None) -> str:
    """
    Build a mention string including:
        • user‑id
        • full name and/or username (when available)
        • account age in days  →  <123d>
        • rating (only when chat_id supplied)  →  (7)

    Example
    -------
    [123] - Nikita Rvachev - @rvnikita - <370d> (5)
    """
    try:
        with db_helper.session_scope() as session:
            user = session.query(db_helper.User).filter_by(id=user_id).first()
            if user is None:
                return f"[{user_id}]"

            # ───────────── name / username ─────────────
            full_name = " ".join(p for p in (user.first_name, user.last_name) if p)
            if full_name and user.username:
                mention = f"[{user.id}] - {full_name} - @{user.username}"
            elif user.username:
                mention = f"[{user.id}] - @{user.username}"
            elif full_name:
                mention = f"[{user.id}] - {full_name}"
            else:
                mention = f"[{user.id}]"

            # ───────────── account age ─────────────
            if user.created_at:
                days_old = (datetime.now(timezone.utc) - user.created_at).days
                mention += f" - <{days_old}d>"
            else:
                mention += " - <N/A>"

            # ───────────── rating (optional) ─────────────
            if chat_id is not None:
                rating = rating_helper.get_rating(user_id, chat_id)
                if rating is not None:
                    mention += f" ({rating})"

            return mention

    except Exception:
        logger.error(
            f"Error generating mention for user_id={user_id}\n{traceback.format_exc()}"
        )
        return f"[{user_id}]"


def db_upsert_user(user_id, chat_id, username, last_message_datetime, first_name=None, last_name=None, raw_user=None):
    try:
        # Generate a unique cache key for the user's data
        cache_key = f"user_{user_id}_chat_{chat_id}"

        # Attempt to retrieve the user's current data from cache
        cached_data = cache_helper.get_key(cache_key)

        # Define the new data for comparison and potential cache update.
        # We include the new raw_user data.
        new_data = {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "last_message_datetime": last_message_datetime,
            "user_raw": raw_user
        }

        # If cached data exists and hasn't changed, skip the DB operation.
        if cached_data and cached_data == new_data:
            return  # Data is up-to-date; no need to hit the DB

        else:
            with db_helper.session_scope() as db_session:
                # Upsert User: include raw_user in both the insert and update dictionaries.
                insert_stmt = insert(db_helper.User).values(
                    id=user_id,
                    created_at=datetime.now(),
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    user_raw=raw_user
                ).on_conflict_do_update(
                    index_elements=['id'],  # Assumes 'id' is the primary key
                    set_=dict(
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        user_raw=raw_user
                    )
                )
                db_session.execute(insert_stmt)

                # Upsert User_Status (unchanged)
                insert_stmt = insert(db_helper.User_Status).values(
                    user_id=user_id,
                    chat_id=chat_id,
                    last_message_datetime=last_message_datetime
                ).on_conflict_do_update(
                    index_elements=['user_id', 'chat_id'],
                    set_=dict(last_message_datetime=last_message_datetime)
                )
                db_session.execute(insert_stmt)

                db_session.commit()

                # Update the cache with the new data (expires in 1 hour)
                cache_helper.set_key(cache_key, new_data, expire=3600)
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
