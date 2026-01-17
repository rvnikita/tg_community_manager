# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based Telegram community manager bot that handles moderation, spam detection, user management, and automated responses for Telegram supergroups. The bot uses PostgreSQL with pgvector for embeddings, machine learning models for spam detection, and integrates with OpenAI for content analysis.

## Key Architecture Components

### Main Entry Points
- `src/dispatcher.py` - Main bot application with Telegram handlers and message processing
- `src/cas_feed_listener.py` - Listens to CAS (Combot Anti-Spam) feeds for global ban updates

### Database Layer
- `src/helpers/db_helper.py` - SQLAlchemy ORM models and database operations
- Uses PostgreSQL with pgvector extension for embedding storage
- Alembic migrations in `alembic/versions/` for schema changes

### Core Helper Modules
- `src/helpers/spamcheck_helper*.py` - Multiple spam detection implementations (ML-based, raw text, structured analysis)
- `src/helpers/openai_helper.py` - OpenAI API integration for text analysis
- `src/helpers/message_helper.py` - Message processing and formatting
- `src/helpers/user_helper.py` - User management and status tracking
- `src/helpers/chat_helper.py` - Chat configuration and permissions
- `src/helpers/embeddings_reply_helper.py` - Vector embeddings for auto-replies
- `src/helpers/reporting_helper.py` - User reporting system

### ML Models and Training
- `ml_models/` - Contains trained scikit-learn models (SVM, scalers)
- `src/cron/antispam_ml*.py` - Various spam detection model training scripts
- Models use different feature extraction approaches (raw text, structured features, embeddings)

### Scheduled Tasks
- `src/cron/` - Contains cron jobs for:
  - Training and updating ML models
  - Updating embeddings for messages and replies  
  - User status maintenance
  - Scheduled message sending
  - Bot permission checks

## Development Commands

### Running the Application
```bash
# Main bot
python3 src/dispatcher.py

# CAS feed listener
python3 src/cas_feed_listener.py
```

### Temporary Scripts

When creating temporary scripts for testing, debugging, or one-off database operations:
- **Always place them in `temp_scripts/` folder** (this folder is gitignored)
- Use descriptive names like `create_test_chain.py`, `debug_spam_check.py`
- Include docstrings explaining what the script does
- These scripts should be self-contained and load environment variables via `dotenv`

Example structure:
```python
#!/usr/bin/env python3
"""Brief description of what this script does"""
import os, sys
from dotenv import load_dotenv
load_dotenv('config/.env')

# Add project root to path (same pattern as cron scripts)
project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.append(os.path.abspath(project_root))

# Import using src.helpers.* pattern
from src.helpers.db_helper import Session
# ... rest of script
```

### Testing
```bash
# Run all tests
pytest

# Run specific test
pytest tests/test_tg_spam_unspam.py
```

### Database Management
```bash
# Run migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"
```

### ML Model Training
```bash
# Train and deploy models
./src/cron/antispam_ml_train_and_push.sh
```

## Database Access

When any task requires database access (queries, debugging, data inspection), always use credentials from `config/.env` file. Load them using `dotenv` before connecting to the database.

## Environment Configuration

The application requires these environment variables:
- `ENV_DB_*` - PostgreSQL database connection parameters
- `BOT_KEY` - Telegram bot token
- `OPENAI_API_KEY` - OpenAI API key for embeddings/analysis
- `TELETHON*_API_*` - Telethon client credentials for user automation
- `SENTRY_DSN` - Error monitoring

## Database Schema Key Points

- **Message_Log** - Stores all messages with embeddings, spam predictions, and manual verification flags
- **User/User_Status** - User information and per-chat status tracking  
- **User_Global_Ban** - Global ban list with reasons
- **Auto_Reply** - Embedding-based automatic response system
- **Scheduled_Message** - Timed message delivery system
- **Report** - User reporting and moderation logs

## Spam Detection Pipeline

The bot implements multiple spam detection approaches:
1. **Raw text analysis** (`spamcheck_helper_raw.py`) - Direct text classification
2. **Structured features** (`spamcheck_helper_raw_structure.py`) - Linguistic feature extraction
3. **Embedding-based** (`antispam_embedding.py`) - Vector similarity analysis
4. **Combined ML models** - SVM classifiers with different feature sets

## Testing Approach

- Uses pytest with asyncio support for async handlers
- Integration tests with real Telegram clients via Telethon
- Database fixtures with test data cleanup
- Tests cover spam/unspam workflows and message processing

## Key Integration Points

- **Telegram Bot API** - Primary interface via python-telegram-bot library
- **Telethon** - For user client operations and advanced Telegram features
- **PostgreSQL + pgvector** - Persistent storage with vector similarity search
- **OpenAI API** - Text embeddings and content analysis
- **Scikit-learn** - ML model training and inference
- **Sentry** - Error monitoring and performance profiling