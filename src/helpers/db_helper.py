from sqlalchemy import create_engine, BigInteger, Boolean, Column, DateTime, Identity, Integer, Float, JSON, PrimaryKeyConstraint, String, Text, UniqueConstraint, text, ForeignKey, Index, Time
from sqlalchemy.orm import Session, DeclarativeBase, declared_attr, relationship, backref
from sqlalchemy.sql.sqltypes import NullType
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from pgvector.sqlalchemy import Vector

import psycopg2
import psycopg2.extras
import os
import inspect #we need this to get current file name path
import traceback
import uuid
import threading
from contextlib import contextmanager

import src.helpers.logging_helper as logging_helper

logger = logging_helper.get_logger()

def connect():
    conn = None
    try:
        conn = psycopg2.connect(user=os.getenv('ENV_DB_USER'),
                                password=os.getenv('ENV_DB_PASSWORD'),
                                host=os.getenv('ENV_DB_HOST'),
                                port=os.getenv('ENV_DB_PORT'),
                                database=os.getenv('ENV_DB_DATABASE'))
        return conn
    except (Exception, psycopg2.DatabaseError) as error:
        #write admin log mentioning file name and error
        logger.error(f"Error: {traceback.format_exc()}")

        return None


class Base(DeclarativeBase):
    __prefix__ = 'tg_'

    @declared_attr
    def __tablename__(cls):
        return cls.__prefix__ + cls.__name__.lower()

class User(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='user_pkey'),
    )

    id = Column(BigInteger, primary_key=True)
    created_at = Column(DateTime(True), server_default=text('now()'))
    #TODO:MED: split name into first_name and last_name
    first_name = Column(String)
    last_name = Column(String)
    username = Column(String)
    is_bot = Column(Boolean)
    is_anonymous = Column(Boolean)
    user_raw = Column(JSON, nullable=True)

    user_statuses = relationship('User_Status', back_populates='user')

class Chat_Group(Base):
    __table_args__ = (PrimaryKeyConstraint('id', name='chat_group_pkey'),)

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)

    chats = relationship('Chat', back_populates='chat_group')


class Chat(Base):
    __table_args__ = (PrimaryKeyConstraint('id', name='chat_pkey'),)

    id = Column(BigInteger, primary_key=True)
    group_id = Column(Integer, ForeignKey(Chat_Group.__table__.c.id), nullable=True)

    """
    Configurations for the chat explained:
    {
      // The words that indicate a positive reaction or agreement to increase user rating
      "like_words": [
        "мерси",
        "спасиб",
        "👍"
      ],

      // The emoji that indicate a positive reaction or agreement to increase user rating
      "like_reactions": [
        "👍",
        "❤️"
      ],

      // The words that indicate a negative reaction or disagreement to decrease user rating
      "dislike_words": [
        "👎"
      ],

      // The emoji that indicate a negative reaction or disagreement to decrease user rating
      "dislike_reactions": [
        "👎"
      ],

      // The maximum number of days of inactivity before a user is removed from the chat. Set to 0 to disable
      "kick_inactive": 90,

      // The number of days of inactivity after which a user is warned about potential removal. Set to 0 to disable
      "warn_inactive": 60,

      // The welcome message for the chat that is posted into chat when a new user joins 
      "welcome_message": "Добро пожаловать в чат",

      // A boolean value that determines if a user's status should be updated or not by cron script
      "update_user_status": true,

      // A boolean value that determines if user status updates should be sent as logger.warning() or not
      "update_user_status_critical": false,

      // The DM sent to welcome a new user
      "welcome_dm_message": "👋 Добро пожаловать в чат",

      // The number of user reports required to ban a user
      //TODO:MID: may be we need to use 0 to disable ban (need to change this in code as well)
      "number_of_reports_to_ban": 4,

      // The number of user reports required to warn a user
      //TODO:MID: may be we need to use 0 to disable warn (need to change this in code as well)
      "number_of_reports_to_warn": 2,

      // A boolean value that determines if bot messages should be deleted from the channel or not
      "delete_channel_bot_message": true,

      // The list of user IDs that are allowed to delete bot messages from the channel
      "delete_channel_bot_message_allowed_ids": [
        -1001120203630
      ],

      // A boolean value that determines if bot messages about joining users should be deleted from the chat or not
      "delete_new_chat_members_message" : true,

      // A boolean value that determines if agressive antispam should be enabled or not
      "agressive_antispam" : true,

      // A boolean value that determines if bot should auto approve join requests or not
      "auto_approve_join_request":false,
      
      // An integer value that determines the power multiplier for the user. For each X ratings the user gets 1 power point (e.g. in reporting system). 0 means default power of 1. 15 means each 15 ratings the user gets 1 power point.
      "user_rating_to_power_ratio": 0,
      
      // A boolean value that determines if spam check with AI should be enabled or not 
      "ai_spam_check_enabled": true
      
      // A boolean value that determines if spam check with new AI model should be enabled or not
      "ai_spamcheck_enabled": true

    }
    """

    config = Column(JSON, nullable=False)
    created_at = Column(DateTime(True), server_default=text('now()'))
    chat_name = Column(String, server_default=text("''::character varying"))
    invite_link = Column(String, server_default=text("''::character varying"))
    last_admin_permission_check = Column(DateTime(True), nullable=True)  # New column for tracking the last admin permission check
    active = Column(Boolean, nullable=False, server_default=text('true'))

    chat_group = relationship('Chat_Group', back_populates='chats')
    user_statuses = relationship('User_Status', back_populates='chat')
    user_ratings = relationship('User_Rating', back_populates='chat')

class Message_Deletion(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='message_deletion_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    chat_id = Column(BigInteger, ForeignKey(Chat.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey(User.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=True, index=True)
    message_id = Column(BigInteger, nullable=False, index=True)
    trigger_id = Column(BigInteger, nullable=True)  # Associates the message with a specific event or trigger
    status = Column(String, nullable=False, server_default=text("'active'::character varying"))  # Default status is 'active', can be updated to 'resolved' or 'deleted'
    added_at = Column(DateTime(True), server_default=text('now()'))  # Timestamp when the record is added to the database
    message_posted_at = Column(DateTime(True), nullable=True)  # Timestamp when the message was originally posted
    scheduled_deletion_time = Column(DateTime(True), nullable=True)  # Timestamp when the message is scheduled to be automatically deleted

    # Relationships (optional, for easier ORM navigation)
    chat = relationship('Chat', foreign_keys=[chat_id])
    user = relationship('User', foreign_keys=[user_id])

    def __repr__(self):
        return f"<Message_Deletion(id={self.id}, chat_id={self.chat_id}, user_id={self.user_id}, message_id={self.message_id}, reply_to_message_id={self.reply_to_message_id}, status='{self.status}', added_at='{self.added_at}', message_posted_at='{self.message_posted_at}', scheduled_deletion_time='{self.scheduled_deletion_time}')>"



class User_Rating(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='user_rating_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1))
    user_id = Column(BigInteger, ForeignKey(User.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True)
    chat_id = Column(BigInteger, ForeignKey(Chat.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True)
    judge_id = Column(BigInteger, ForeignKey(User.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True)
    change_value = Column(Integer, nullable=False)
    change_date = Column(DateTime(True), server_default=text('now()'))

    user = relationship('User', foreign_keys=[user_id])
    chat = relationship('Chat', back_populates='user_ratings')
    judge = relationship('User', foreign_keys=[judge_id])




class User_Status(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='user_status_pkey'),
        UniqueConstraint('user_id', 'chat_id', name='unique_cols'),
        Index('ix_user_status_user_id', 'user_id') # To make SELECT * FROM tg_user_status WHERE user_id = $1 faster
    )

    id = Column(BigInteger, Identity(start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1))
    created_at = Column(DateTime(True), server_default=text('now()'))
    user_id = Column(BigInteger, ForeignKey(User.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True)
    chat_id = Column(BigInteger, ForeignKey(Chat.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True)
    last_message_datetime = Column(DateTime(True))
    status = Column(String)

    user = relationship('User', back_populates='user_statuses')
    chat = relationship('Chat', back_populates='user_statuses')

class User_Global_Ban(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='user_global_ban_pkey'),
    )

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey(User.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True, unique=True)
    created_at = Column(DateTime(True), server_default=text('now()'))
    reason = Column(String)

#TODO:LOW: rename to User_Report
class Report(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='report_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1))
    reported_user_id = Column(BigInteger, nullable=False, index=True)
    reporting_user_id = Column(BigInteger, nullable=False, index=True)
    reported_message_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    report_power = Column(Integer, nullable=False, default=1)  # New attribute to store report power
    created_at = Column(DateTime(True), server_default=text('now()'))
    reason = Column(String, nullable=True)


class Message_Log(Base):
    __table_args__ = (
        UniqueConstraint('message_id', 'chat_id', name='uix_message_id_chat_id'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(BigInteger, index=True)
    chat_id = Column(BigInteger, ForeignKey(Chat.__table__.c.id), nullable=False)
    raw_message = Column(JSON, nullable=True)
    message_content = Column(Text)
    user_id = Column(BigInteger, ForeignKey(User.__table__.c.id), nullable=False)
    user_nickname = Column(Text)
    user_current_rating = Column(Integer)
    message_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    is_spam = Column(Boolean, default=False, nullable=False)
    action_type = Column(Text)
    reporting_id = Column(BigInteger, ForeignKey(User.__table__.c.id), nullable=True)
    reporting_id_nickname = Column(Text, nullable=True)
    reason_for_action = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    embedding = Column(Vector, nullable=True)  # Column to store message embeddings
    image_description = Column(Text, nullable=True)
    image_description_embedding = Column(Vector, nullable=True)
    used_for_training = Column(Boolean, default=False, nullable=False)
    manually_verified = Column(Boolean, default=False, nullable=False)
    is_forwarded = Column(Boolean, nullable=True)  # Column to store is message is forwarded
    reply_to_message_id = Column(BigInteger, nullable=True)  # Column to store reply-to message ID
    spam_prediction_probability = Column(Float, nullable=True)  # Column to store spam prediction probability. We are not going to use that for spam prediction itself, but for logging purposes and easier filtering of messages for manual verification


    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="message_logs")
    chat = relationship("Chat", foreign_keys=[chat_id], backref="message_logs")
    admin = relationship("User", foreign_keys=[reporting_id], backref="admin_message_logs")

    def __repr__(self):
        return f"<Message_Log(id={self.id}, message_id={self.message_id}, chat_id={self.chat_id}, user_id={self.user_id}, action_type='{self.action_type}', created_at={self.created_at})>"



#TODO: MED: I think we need to refactor this to split between trigger+reply and other configs. As a result we don't copy the same trigger+reply for each chat
class Auto_Reply(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='auto_reply_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    chat_id = Column(BigInteger, ForeignKey(Chat.__table__.c.id), nullable=False)
    trigger = Column(Text, nullable=False)
    reply = Column(Text, nullable=False)
    last_reply_time = Column(DateTime(True), nullable=True)  # To ensure delay between replies
    reply_delay = Column(Integer, nullable=True)  # Delay in seconds
    usage_count = Column(Integer, default=0)  # New column to track usage count
    enabled = Column(Boolean, nullable=False, server_default=text("true"))

class Embeddings_Auto_Reply_Content(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='embeddings_auto_reply_content_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    reply = Column(Text, nullable=False)
    last_reply_time = Column(DateTime(True), nullable=True)
    reply_delay = Column(Integer, nullable=True)  # in seconds
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime(True), server_default=text('now()'))

    triggers = relationship('Embeddings_Auto_Reply_Trigger', back_populates='content')


class Embeddings_Auto_Reply_Trigger(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='embeddings_auto_reply_trigger_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    chat_id = Column(BigInteger, ForeignKey(Chat.__table__.c.id), nullable=False)
    content_id = Column(BigInteger, ForeignKey(Embeddings_Auto_Reply_Content.id), nullable=False)
    trigger_text = Column(Text, nullable=False)
    embedding = Column(Vector, nullable=True)
    created_at = Column(DateTime(True), server_default=text('now()'))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))

    content = relationship('Embeddings_Auto_Reply_Content', back_populates='triggers')
    chat = relationship('Chat')



class Scheduled_Message_Content(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='scheduled_message_content_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    content = Column(Text, nullable=False)
    parse_mode = Column(String, nullable=True)  # 'Markdown', 'HTML', or None

    # Relationships
    scheduled_message_configs = relationship('Scheduled_Message_Config', back_populates='message_content')

    def __repr__(self):
        # Show only the first 20 characters to keep the output concise
        content_preview = self.content[:20] + '...' if len(self.content) > 20 else self.content
        return f"<ScheduledMessageContent(id={self.id}, content='{content_preview}', parse_mode='{self.parse_mode}')>"


class Scheduled_Message_Config(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='scheduled_message_config_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    chat_id = Column(BigInteger, ForeignKey(Chat.id), nullable=False)
    message_content_id = Column(BigInteger, ForeignKey(Scheduled_Message_Content.id), nullable=False)
    frequency_seconds = Column(Integer, nullable=False)
    last_sent = Column(DateTime(True), nullable=True)
    time_of_the_day = Column(Time, nullable=True)
    day_of_the_week = Column(Integer, nullable=True)
    day_of_the_month = Column(Integer, nullable=True)
    status = Column(String, default='active', nullable=False)
    error_message = Column(Text, nullable=True)
    error_count = Column(Integer, default=0, nullable=False)

    # Relationships
    message_content = relationship('Scheduled_Message_Content', back_populates='scheduled_message_configs')

    def __repr__(self):
        return (f"<ScheduledMessageConfig(id={self.id}, chat_id={self.chat_id}, "
                f"message_content_id={self.message_content_id}, status='{self.status}', "
                f"frequency_seconds={self.frequency_seconds}, time_of_the_day={self.time_of_the_day}, "
                f"day_of_the_week={self.day_of_the_week}, day_of_the_month={self.day_of_the_month}, "
                f"last_sent={self.last_sent}, error_count={self.error_count})>")






db_engine = create_engine(f"postgresql://{os.getenv('ENV_DB_USER')}:{os.getenv('ENV_DB_PASSWORD')}@{os.getenv('ENV_DB_HOST')}:{os.getenv('ENV_DB_PORT')}/{os.getenv('ENV_DB_DATABASE')}",
                          pool_size = 10,
                          max_overflow = 20)
Session = sessionmaker(bind=db_engine)

# Global counter for open sessions
open_session_count = 0
session_count_lock = threading.Lock()


@contextmanager
def session_scope():
    # global open_session_count

    # session_id = uuid.uuid4()  # Generate a unique session identifier for logging purposes
    # with session_count_lock:
    #     open_session_count += 1
    # logger.info(f"Starting a new database session {session_id}. Open sessions: {open_session_count}")

    session = Session()

    try:
        yield session
        session.commit()
        # logger.info(f"Session {session_id} committed successfully.")
    except Exception as error:
        session.rollback()
        # logger.error(f"Session {session_id} rollback due to error: {error}", exc_info=True)
        raise
    finally:
        session.close()
        # with session_count_lock:
            # open_session_count -= 1
        # logger.info(f"Database session {session_id} closed. Open sessions: {open_session_count}")