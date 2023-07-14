# tg-community-manager

The tg-community-manager is a robust Python bot that helps maintain and moderate a supergroup chat on Telegram. It is built using the python-telegram-bot library and offers functionalities such as member handling, user status updates, thank you message handling, report handling, chat join requests, and a robust spam checking mechanism.

This bot employs a PostgreSQL database for persistent data storage and SQLAlchemy ORM for database operations. The **db_helper.py** file contains all the database-related operations including SQLAlchemy ORM model definitions, database connection establishment, session handling, and more.

## Features

- **New Member Management**: Deletes new member messages to keep the chat clean and uncluttered.
- **User Status Updates**: Monitors all chat messages and member additions in the supergroup and updates the user status accordingly.
- **Thank You Message Handling**: Checks if a user sends a thank you message in the chat.
- **Report Handling**: Processes member reports of messages using the /report command.
- **Chat Join Requests**: Handles new chat join requests and processes them accordingly.
- **Ban Commands**: Supports /ban, /global_ban, and /gban commands in the supergroup to ban offending users.
- **Spam Checking**: Checks each text and document message for spam and takes appropriate action if spam is detected.

## Database Model

The bot uses several database tables to handle its operations:
 - Chat: Stores the chat configurations and details.
 - Qna: Holds data for question and answer pairs.
 - User: Keeps track of user data, such as first and last names, whether they are a bot, and whether they are anonymous.
 - User_Status: Keeps track of the status of users in various chats, their ratings, and the time of their last message.
 - User_Global_Ban: Contains information about global bans applied to users.
 - Report: Stores report details of users reporting other users' messages.

## Usage
To run the tg-community-manager bot, make sure you have Python 3 and pip installed on your system. Then, install the required dependencies using pip:
    
    pip install -r requirements.txt

Then, you can run the bot with the following command:

    python3 main.py

Remember to replace 'BOT_KEY' in the config dictionary with your actual bot token obtained from BotFather on Telegram.

## Contributing
Contributions, issues, and feature requests are welcome. Feel free to check the [issues page](https://github.com/rvnikita/tg_community_manager/issues) if you want to contribute.

For major changes, please open an issue first to discuss what you would like to change. Please make sure to update tests as appropriate.

## License
This project is licensed under the terms of the Apache License 2.0.
