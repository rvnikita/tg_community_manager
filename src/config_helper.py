import os
import configparser

def get_config():
    config = configparser.SafeConfigParser(os.environ)
    config_path = os.path.dirname(__file__) + '/../config/' #we need this trick to get path to config folder
    config.read(config_path + 'settings.ini')
    return config