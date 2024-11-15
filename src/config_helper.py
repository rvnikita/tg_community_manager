import os
import configparser
from dotenv import load_dotenv

def get_config():
    # Load environment variables from .env
    load_dotenv()

    # Create a ConfigParser object with environment variable interpolation
    config = configparser.ConfigParser(os.environ)

    # Resolve the path to the settings.ini file
    config_path = os.path.join(os.path.dirname(__file__), '../config/settings.ini')

    # Read the settings.ini file
    config.read(config_path)

    return config
