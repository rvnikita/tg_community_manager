import src.logging_helper as logging_helper
import src.config_helper as config_helper

from sqlalchemy import create_engine, BigInteger, Boolean, Column, DateTime, Identity, Integer, JSON, PrimaryKeyConstraint, String, Text, UniqueConstraint, text, ForeignKey
from sqlalchemy.orm import Session, DeclarativeBase, declared_attr, relationship
from sqlalchemy.sql.sqltypes import NullType

import psycopg2
import psycopg2.extras
import os
import inspect #we need this to get current file name path
import traceback
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


class Chat(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='chat_pkey'),
    )

    id = Column(BigInteger, primary_key=True)

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
      
    }
    """

    config = Column(JSON, nullable=False)
    created_at = Column(DateTime(True), server_default=text('now()'))
    chat_name = Column(String, server_default=text("''::character varying"))

    user_statuses = relationship('User_Status', back_populates='chat')


class Qna(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='qna_pkey'),
    )

    id = Column(BigInteger, primary_key=True)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=text('now()'))
    embedding = Column(NullType)


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


class User_Status(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='user_status_pkey'),
        UniqueConstraint('user_id', 'chat_id', name='unique_cols')
    )

    id = Column(BigInteger, Identity(start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1))
    created_at = Column(DateTime(True), server_default=text('now()'))
    user_id = Column(BigInteger, ForeignKey(User.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True)
    chat_id = Column(BigInteger, ForeignKey(Chat.__table__.c.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False, index=True)
    last_message_datetime = Column(DateTime(True))
    status = Column(String)
    rating = Column(Integer, default=0)

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
    created_at = Column(DateTime(True), server_default=text('now()'))

session = None

@contextmanager
def session_scope():
    #[DB]
# DB_DATABASE=%(ENV_DB_NAME)s
# DB_HOST=%(ENV_DB_HOST)s
# DB_PASSWORD=%(ENV_DB_PASSWORD)s
# DB_PORT=%(ENV_DB_PORT)s
# DB_USER=%(ENV_DB_USER)s
    db_engine = create_engine(f"postgresql://{config['DB']['DB_USER']}:{config['DB']['DB_PASSWORD']}@{config['DB']['DB_HOST']}:{config['DB']['DB_PORT']}/{config['DB']['DB_DATABASE']}")
    session = Session(db_engine)

    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()