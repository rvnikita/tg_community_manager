from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func
import traceback
from datetime import datetime, timezone

import src.helpers.db_helper as db_helper
import src.helpers.logging_helper as logging_helper
import src.helpers.cache_helper as cache_helper
import src.helpers.rating_helper as rating_helper


logger = logging_helper.get_logger()

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


async def get_user_info_text(user_id: int, chat_id: int) -> str:
    """
    Generate formatted user info text for /info command and InfoAction.

    Returns a formatted string with user details including:
    - Username and full name
    - Days since account creation
    - Rating in the chat
    - Message counts (this chat and all chats)

    Args:
        user_id: Telegram user ID
        chat_id: Telegram chat ID

    Returns:
        Formatted info text string
    """
    with db_helper.session_scope() as session:
        u = session.query(db_helper.User).filter_by(id=user_id).first()
        if not u:
            return f"No data for user {user_id}."

        created_at = u.created_at or datetime.now(timezone.utc)
        first_name = u.first_name or ''
        last_name = u.last_name or ''
        username = u.username

    now = datetime.now(timezone.utc)
    days_since = (now - created_at).days
    rating = rating_helper.get_rating(user_id, chat_id)

    # count messages and find interacted users
    with db_helper.session_scope() as session:
        chat_count = session.query(func.count(db_helper.Message_Log.id)) \
                            .filter(db_helper.Message_Log.user_id == user_id,
                                    db_helper.Message_Log.chat_id == chat_id) \
                            .scalar() or 0
        total_count = session.query(func.count(db_helper.Message_Log.id)) \
                             .filter(db_helper.Message_Log.user_id == user_id) \
                             .scalar() or 0

        # Find users who interacted with this person via replies
        # Create aliases for self-join
        from sqlalchemy.orm import aliased
        msg = aliased(db_helper.Message_Log)
        target_msg = aliased(db_helper.Message_Log)

        # Users this person replied to
        replied_to_ids = session.query(target_msg.user_id.distinct()) \
            .join(msg, msg.reply_to_message_id == target_msg.message_id) \
            .filter(
                msg.user_id == user_id,
                msg.chat_id == chat_id,
                target_msg.user_id != user_id
            ).all()

        # Users who replied to this person
        replied_by_ids = session.query(msg.user_id.distinct()) \
            .join(target_msg, msg.reply_to_message_id == target_msg.message_id) \
            .filter(
                target_msg.user_id == user_id,
                msg.chat_id == chat_id,
                msg.user_id != user_id
            ).all()

        # Combine and deduplicate
        interacted_user_ids = set()
        for (uid,) in replied_to_ids:
            interacted_user_ids.add(uid)
        for (uid,) in replied_by_ids:
            interacted_user_ids.add(uid)

        # Get usernames (limit to 10)
        interacted_usernames = []
        if interacted_user_ids:
            users = session.query(db_helper.User).filter(
                db_helper.User.id.in_(list(interacted_user_ids)[:10])
            ).all()

            for u in users:
                if u.username:
                    interacted_usernames.append(f"@{u.username}")

    full_name = (first_name + ' ' + last_name).strip() or '[no name]'

    info_text = (
        f"👤 {'@'+username if username else '[no username]'}\n"
        f"🪪 {full_name}\n"
        f"📅 Joined: {days_since} days ago\n"
        f"⭐ Rating: {rating}\n"
        f"✉️ Messages (this chat): {chat_count}\n"
        f"✉️ Messages (all chats): {total_count}"
    )

    # Add interaction info if available
    if interacted_usernames:
        info_text += f"\n🤝 Possible people who can know: {', '.join(interacted_usernames)}"

    return info_text
