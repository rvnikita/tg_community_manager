from time import time

from src.config_helper import get_config
from src.logging_helper import get_logger

config = get_config()
logger = get_logger()

# In-memory cache dictionary
# Now storing each value as a tuple (actual_value, expiration_timestamp)
cache = {}

def get_key(key):
    try:
        if key in cache:
            value, expire_at = cache[key]
            if time() > expire_at:
                # Key has expired, so remove it and return None
                del cache[key]
                return None
            return value
        return None
    except Exception as e:
        logger.error(f"Failed to get key {key} from cache: {e}")
        return None

def set_key(key, value, expire=None):
    try:
        expire_at = time() + expire if expire is not None else float('inf')  # Use 'inf' for no expiration
        cache[key] = (value, expire_at)
        # logger.info(f"Set key {key} in cache with value {value} and expiration {expire_at}")
    except Exception as e:
        logger.error(f"Failed to set key {key} in cache: {e}")

def delete_key(key):
    try:
        # Check if the key exists and remove it
        if key in cache:
            del cache[key]
            logger.info(f"Deleted key {key} from cache.")
    except Exception as e:
        logger.error(f"Failed to delete key {key} from cache: {e}")
