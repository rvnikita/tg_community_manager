import src.logging_helper as logging_helper
import src.config_helper as config_helper

from sqlalchemy import create_engine, BigInteger, Boolean, Column, DateTime, Identity, Integer, JSON, PrimaryKeyConstraint, String, Text, UniqueConstraint, text, ForeignKey, Index
from sqlalchemy.orm import Session, DeclarativeBase, declared_attr, relationship
from sqlalchemy.sql.sqltypes import NullType
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func

import psycopg2
import psycopg2.extras
import os
import inspect #we need this to get current file name path
import traceback
import uuid
import threading
from contextlib import contextmanager

config = config_helper.get_config()

logger = logging_helper.get_logger()

def connect():
    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'], cursor_factory=psycopg2.extras.RealDictCursor)
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
    #TODO:MID: split name into first_name and last_name
    first_name = Column(String)
    last_name = Column(String)
    username = Column(String)
    is_bot = Column(Boolean)
    is_anonymous = Column(Boolean)

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
      "agressive_antispam" : true

      // A boolean value that determines if bot should auto approve join requests or not
      "auto_approve_join_request":false
      
      // An integer value that determines the power multiplier for the user. For each X ratings the user gets 1 power point (e.g. in reporting system)
      "user_rating_to_power_ratio": 15

    }
    """

    config = Column(JSON, nullable=False)
    created_at = Column(DateTime(True), server_default=text('now()'))
    chat_name = Column(String, server_default=text("''::character varying"))
    invite_link = Column(String, server_default=text("''::character varying"))

    chat_group = relationship('Chat_Group', back_populates='chats')
    user_statuses = relationship('User_Status', back_populates='chat')
    user_ratings = relationship('User_Rating', back_populates='chat')

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



class Qna(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='qna_pkey'),
    )

    id = Column(BigInteger, primary_key=True)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=text('now()'))
    embedding = Column(NullType)


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

db_engine = create_engine(f"postgresql://{config['DB']['DB_USER']}:{config['DB']['DB_PASSWORD']}@{config['DB']['DB_HOST']}:{config['DB']['DB_PORT']}/{config['DB']['DB_DATABASE']}",
                          pool_size = 10,
                          max_overflow = 20)
Session = sessionmaker(bind=db_engine)

# Global counter for open sessions
open_session_count = 0
session_count_lock = threading.Lock()


@contextmanager
def session_scope():
    global open_session_count

    session_id = uuid.uuid4()  # Generate a unique session identifier for logging purposes
    with session_count_lock:
        open_session_count += 1
    logger.info(f"Starting a new database session {session_id}. Open sessions: {open_session_count}")

    session = Session()

    try:
        yield session
        session.commit()
        # logger.info(f"Session {session_id} committed successfully.")
    except Exception as error:
        session.rollback()
        logger.error(f"Session {session_id} rollback due to error: {error}", exc_info=True)
        raise
    finally:
        session.close()
        with session_count_lock:
            open_session_count -= 1
        # logger.info(f"Database session {session_id} closed. Open sessions: {open_session_count}")