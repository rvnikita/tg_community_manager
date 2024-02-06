from src.config_helper import get_config
from src.logging_helper import get_logger

import redis
import ssl

config = get_config()
logger = get_logger()

def get_redis_connection():
    # Create an SSL context for the Redis connection
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)

    # Specify the path to your CA certificate file if needed
    # ssl_context.load_verify_locations(cafile='/path/to/ca_certificate.pem')

    return redis.Redis(
        host=config['REDIS']['REDIS_HOST'],
        port=config['REDIS']['REDIS_PORT'],
        db=config['REDIS']['REDIS_DB'],
        password=config['REDIS']['REDIS_PASSWORD'],
        decode_responses=True,
        ssl=ssl_context  # Pass the SSL context to enable SSL/TLS
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
