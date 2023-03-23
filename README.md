# Telegram Community Manager

This is a Telegram bot built using [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) python library. 
The bot listens for new messages in groups and does some acitons. 

## Features
- Delete messages when user joins the chat
- Update user status in the database
- Auto respond to questions in chats with answers based on predefined vector embeddings with OpenAI ChatGPT support [BETA]

## Dependencies
- Python
- Telegram bot API
- python-telegram-bot
- OpenAI API
- psycopg2

## Usage
- Install the required dependencies.
- Set up the required environment variables and API keys.
- Update the config_helper.py file with your configuration settings.
- Run the dispatcher.py script.
- Add the bot to your desired chats as an Administrator
- The bot will automatically listen for new messages and respond accordingly.
