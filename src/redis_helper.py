from src.config_helper import get_config
from src.logging_helper import get_logger

import redis

config = get_config()
logger = get_logger()


def get_redis_connection():
    redis_url = config['REDIS']['REDIS_URL']

    if not redis_url:
        logger.error("REDIS_URL environment variable not found.")
        return None

    return redis.Redis.from_url(redis_url, decode_responses=True)

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
