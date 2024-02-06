from src.config_helper import get_config
from src.logging_helper import get_logger

import redis

config = get_config()
logger = get_logger()

def get_redis_connection():
    return redis.Redis(
        host=config['REDIS']['REDIS_HOST'],
        port=config['REDIS']['REDIS_PORT'],
        db=config['REDIS']['REDIS_DB'],
        password=config['REDIS']['REDIS_PASSWORD'],
        decode_responses=True
    )

def get_key(key):
    try:
        r = get_redis_connection()
        return r.get(key)
    except Exception as e:
        logger.error(f"Failed to get key {key} from Redis: {e}")
        return None

def set_key(key, value, expire=None):
    try:
        r = get_redis_connection()
        r.set(key, value, ex=expire)
    except Exception as e:
        logger.error(f"Failed to set key {key} in Redis: {e}")
