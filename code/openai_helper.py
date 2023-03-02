import openai
import os
import configparser

config = configparser.ConfigParser()
config_path = os.path.dirname(__file__) + '/../config/' #we need this trick to get path to config folder
config.read(config_path + 'openai.ini')

openai.api_key = config['OPENAI']['KEY']

def generate_embedding(text):
    response = openai.Embedding.create(
        engine=config['OPENAI']['EMBEDDING_MODEL'],
        input=text
    )

    return response

