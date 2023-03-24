from src.admin_log import admin_log
import src.config_helper as config_helper

from sqlalchemy import create_engine, BigInteger, Boolean, Column, DateTime, Identity, Integer, JSON, PrimaryKeyConstraint, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Session, DeclarativeBase, declared_attr
from sqlalchemy.sql.sqltypes import NullType

import psycopg2
import psycopg2.extras
import os
import inspect #we need this to get current file name path

config = config_helper.get_config()

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
        admin_log(f"Error in {__file__}: while connecting to PostgreSQL: {error}", critical=True)

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

    id = Column(BigInteger, Identity(start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1))
    chat_id = Column(BigInteger, nullable=False)
    config = Column(JSON, nullable=False)
    created_at = Column(DateTime(True), server_default=text('now()'))
    chat_name = Column(String, server_default=text("''::character varying"))


class Qna(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='qna_pkey'),
    )

    id = Column(Integer)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=text('now()'))
    embedding = Column(NullType)


class User(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='user_pkey'),
    )

    id = Column(BigInteger)
    username = Column(String)
    last_message_datetime = Column(DateTime(True))
    name = Column(String)
    status = Column(String)
    is_bot = Column(Boolean)
    is_anonymous = Column(Boolean)


class User_Status(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='user_status_pkey'),
        UniqueConstraint('user_id', 'chat_id', name='unique_cols')
    )

    id = Column(BigInteger, Identity(start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1))
    user_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(True), server_default=text('now()'))
    chat_id = Column(BigInteger)
    last_message_datetime = Column(DateTime(True))
    status = Column(String)


class Words(Base):
    __table_args__ = (
        PrimaryKeyConstraint('id', name='words_pkey'),
    )

    id = Column(BigInteger, Identity(start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1))
    chat_id = Column(BigInteger, nullable=False)
    word = Column(String, nullable=False)
    created_at = Column(DateTime(True), server_default=text('now()'))
    category = Column(BigInteger)
    embedding = Column(NullType)

#connect to postgresql
engine = create_engine(f"postgresql://{config['DB']['DB_USER']}:{config['DB']['DB_PASSWORD']}@{config['DB']['DB_HOST']}:{config['DB']['DB_PORT']}/{config['DB']['DB_DATABASE']}")

session = Session(engine)