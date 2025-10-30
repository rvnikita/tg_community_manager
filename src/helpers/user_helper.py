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

def extract_user_id_from_command(message, command_parts, allow_reply=True):
    """
    Extract user ID from a command message using multiple methods:
    1. Reply to message (if allow_reply=True)
    2. Direct user ID as argument
    3. Username with @ prefix as argument

    Args:
        message: The telegram message object
        command_parts: List of command parts (message.text.split())
        allow_reply: Whether to check for reply_to_message (default: True)

    Returns:
        int: User ID if found
        None: If no user could be identified
    """
    try:
        # Method 1: Extract from reply
        if allow_reply and message.reply_to_message:
            return message.reply_to_message.from_user.id

        # Method 2 & 3: Extract from command arguments
        if len(command_parts) >= 2:
            user_identifier = command_parts[1]

            # Method 2: Direct user ID
            if user_identifier.isdigit():
                return int(user_identifier)

            # Method 3: Username with @ prefix
            if '@' in user_identifier:
                username = user_identifier[1:] if user_identifier.startswith('@') else user_identifier
                return get_user_id(username=username)

        return None
    except Exception as e:
        logger.error(f"Error extracting user ID from command: {e}. Traceback: {traceback.format_exc()}")
        return None

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
        # Prioritize non-banned users with least spam, then by interaction count
        from sqlalchemy.orm import aliased
        from sqlalchemy import case

        msg = aliased(db_helper.Message_Log)
        target_msg = aliased(db_helper.Message_Log)
        spam_log = aliased(db_helper.Message_Log)

        # Build query to count interactions and spam messages
        # This finds all reply interactions (both directions) and counts them
        interacted_users = session.query(
            db_helper.User,
            func.count(msg.id).label('interaction_count'),
            func.coalesce(
                func.sum(case((spam_log.is_spam == True, 1), else_=0)),
                0
            ).label('spam_count')
        ).select_from(msg).join(
            target_msg,
            msg.reply_to_message_id == target_msg.message_id
        ).join(
            db_helper.User,
            # Join the other user (not the target user_id)
            db_helper.User.id == case(
                (msg.user_id == user_id, target_msg.user_id),
                else_=msg.user_id
            )
        ).outerjoin(
            db_helper.User_Global_Ban,
            db_helper.User.id == db_helper.User_Global_Ban.user_id
        ).outerjoin(
            spam_log,
            (spam_log.user_id == db_helper.User.id) &
            (spam_log.chat_id == chat_id)
        ).filter(
            # Either this person replied to someone, or someone replied to this person
            ((msg.user_id == user_id) | (target_msg.user_id == user_id)),
            # In this specific chat
            msg.chat_id == chat_id,
            # Don't match self-replies
            msg.user_id != target_msg.user_id,
            # Exclude globally banned users
            db_helper.User_Global_Ban.user_id.is_(None),
            # Only users with usernames
            db_helper.User.username.isnot(None)
        ).group_by(
            db_helper.User.id
        ).order_by(
            func.coalesce(
                func.sum(case((spam_log.is_spam == True, 1), else_=0)),
                0
            ).asc(),  # Least spam first (0, 1, 2, ...)
            func.count(msg.id).desc()  # Then most interactions
        ).limit(10).all()

        # Format usernames with rating
        interacted_usernames = [
            f"@{user.username}({rating_helper.get_rating(user.id, chat_id)})"
            for user, interaction_count, spam_count in interacted_users
        ]

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
