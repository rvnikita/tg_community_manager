# Spam Detection System

This document describes the spam detection system used by the Telegram community manager bot.

## Overview

The bot uses a multi-layered approach to spam detection:

1. **Aggressive Antispam** - Rule-based checks (language filters, APK files, story redirects)
2. **ML-based Spam Detection** - Machine learning models trained on message data
3. **CAS Integration** - Combot Anti-Spam global ban list
4. **User Verification** - Manually verified users bypass spam actions

## Spam Detection Pipeline

```
Message arrives
    │
    ▼
Admin check → Skip if admin
    │
    ▼
User 777000 check → Skip if Telegram service account
    │
    ▼
Anonymous bot check → Skip if GroupAnonymousBot
    │
    ▼
Aggressive antispam (if enabled):
    ├── Language filter (ar, fa, ur, he, etc.)
    ├── APK file detection
    └── Story redirect detection
    │
    ▼
User verification check → If verified: log prediction, skip action
    │
    ▼
ML Spam Prediction:
    ├── Generate text embedding (OpenAI)
    ├── Generate image description embedding (if applicable)
    └── Run spam prediction model
    │
    ▼
Moderation action based on probability thresholds:
    ├── delete_thr (default: 0.8) → Delete message
    └── mute_thr (default: 0.95) → Delete + mute user globally
```

## ML Models

### Current Model: XGBoost

The primary spam detection model uses **XGBoost** (`antispam_ml_optimized.py`):
- Gradient boosting classifier with 100 estimators
- Handles missing values (NULL/NaN) natively
- Model files: `ml_models/xgb_spam_model.joblib`, `ml_models/scaler.joblib`

### Training Data Sources

Messages are used for training based on these criteria:

```sql
-- Training data selection (from antispam_ml_optimized.py)
WHERE embedding IS NOT NULL
  AND message_content IS NOT NULL
  AND is_spam IS NOT NULL  -- Only use verified labels (true/false), exclude unknown (NULL)
  AND (
      manually_verified = true
      OR (spam_prediction_probability > 0.99 AND is_spam = true)
      OR (spam_prediction_probability < 0.01 AND is_spam = false)
  )
ORDER BY id DESC  -- Most recent messages first
```

### Legacy Model Types

1. **Raw Text Model** (`spamcheck_helper_raw.py`)
   - Direct text classification
   - Uses text embeddings

2. **Structured Features Model** (`spamcheck_helper_raw_structure.py`)
   - Linguistic feature extraction
   - Combines structural features with embeddings

3. **Combined Model** (`spamcheck_helper.py`)
   - Uses both text and image description embeddings

## User Verification System

### Purpose

Verified users are exempt from spam actions. Their messages:
- Still get spam prediction calculated
- Are logged with `is_spam=False`, `manually_verified=True`
- Include prediction probability in the reason field
- **Never get deleted or muted**

This is useful for:
- Trusted community members who post legitimate content that might look like spam
- Members of closed/invite-only groups where all users can be considered trusted
- Building clean training data from known non-spam sources

### Commands

| Command | Aliases | Description |
|---------|---------|-------------|
| `/verify_user @username` | `/vu` | Mark user as verified (super admin only) |
| `/unverify_user @username` | `/uvu` | Remove verification (super admin only) |

Commands work in:
- Direct messages to the bot
- Group chats

### Database

User verification is stored in the `tg_user` table:

```sql
-- Check if user is verified
SELECT is_verified FROM tg_user WHERE id = <user_id>;

-- Verify a user
UPDATE tg_user SET is_verified = true WHERE id = <user_id>;

-- Verify all users from a specific chat (bulk operation)
UPDATE tg_user SET is_verified = true
WHERE id IN (
    SELECT DISTINCT user_id FROM tg_user_status WHERE chat_id = <chat_id>
);
```

## Manual Message Verification

### Marking Messages as Spam/Not Spam

| Command | Aliases | Description |
|---------|---------|-------------|
| `/spam @username` | `/s` | Mark message as spam and ban user globally |
| `/unspam @username` | `/us` | Unspam user: unban, unmute, update logs |

### Message Log Fields

| Field | Description |
|-------|-------------|
| `is_spam` | Spam classification: `NULL`=unknown, `false`=not spam, `true`=spam |
| `manually_verified` | Whether classification was manually verified |
| `spam_prediction_probability` | ML model's spam probability (0-1) |
| `reason_for_action` | Human-readable reason for classification |

### is_spam Semantics

The `is_spam` column uses three-state logic:

| Value | Meaning | Used for Training |
|-------|---------|-------------------|
| `NULL` | Unknown/not classified | No |
| `false` | Verified as not spam | Yes |
| `true` | Verified as spam | Yes |

Important: Only messages with `is_spam = true` or `is_spam = false` are used for ML training. Messages with `is_spam = NULL` are excluded to prevent polluting the training data with unverified classifications.

## ML Features

### Feature List (Total: 3092 dimensions)

The XGBoost spam detection model uses the following features in order:

#### Embedding Features (3072d)

| Feature | Type | Description |
|---------|------|-------------|
| `embedding` | Vector (1536d) | OpenAI text embedding of message content |
| `image_description_embedding` | Vector (1536d) | OpenAI embedding of image description (zero vector if no image) |

#### User & Context Features (7)

| Feature | Type | Description |
|---------|------|-------------|
| `user_current_rating` | Integer | User's rating in the chat |
| `time_difference` | Float | Seconds since user joined the chat |
| `chat_id` | Integer | Chat ID (different chats have different spam norms) |
| `log10(user_id)` | Float | Log10 of Telegram user ID (proxy for account age: higher ID = newer account) |
| `message_length` | Integer | Length of message text |
| `spam_count` | Integer | User's previous spam messages count |
| `not_spam_count` | Integer | User's previous non-spam messages count |

#### Message Behavior Features (7)

| Feature | Type | Description |
|---------|------|-------------|
| `is_forwarded` | Binary (0/1) | Whether message is forwarded |
| `is_reply` | Binary (0/1) | Whether message is a reply to another message |
| `has_telegram_nick` | Binary (0/1) | Whether message contains @username mention |
| `has_image` | Binary (0/1) | Whether message has an analyzed image with embedding |
| `has_username` | Binary (0/1) | Whether the user has a Telegram username set |
| `hour_utc` | Float (0-23) | Hour of day when message was sent (UTC) |
| `day_of_week` | Float (0-6) | Day of week (0=Monday, 6=Sunday) |

#### Media & Entity Features (6)

| Feature | Type | Description |
|---------|------|-------------|
| `has_video` | Boolean/NULL | Whether message has video or animation/GIF |
| `has_document` | Boolean/NULL | Whether message has document attachment |
| `has_photo` | Boolean/NULL | Whether message has photo |
| `forwarded_from_channel` | Boolean/NULL | Whether forwarded from a channel (vs user/group) |
| `has_link` | Boolean/NULL | Whether message contains URL links |
| `entity_count` | Integer/NULL | Number of entities (links, mentions, etc.) |

### Feature Spam Signals

| Feature | Spam Signal | Rationale |
|---------|-------------|-----------|
| `log10(user_id)` | **VERY HIGH** | Newer accounts (higher IDs) are 98% spam vs 20% for old accounts |
| `has_video` | HIGH | Porn/scam spam often uses video content |
| `has_document` | MEDIUM | Document attachments can be malicious (APK, etc.) |
| `has_photo` | LOW | Photos are common but less indicative alone |
| `forwarded_from_channel` | HIGH | Channel forwards are higher risk than user forwards |
| `has_link` | MEDIUM | Links often indicate promotional spam |
| `entity_count` | MEDIUM | Many entities (links, mentions) = suspicious |
| `has_username` | LOW | Users without usernames are slightly more suspicious |
| `is_reply` | LOW | Replies to existing messages are less likely spam |
| `hour_utc` | LOW | Some spam campaigns target specific time windows |
| `day_of_week` | LOW | Weekend vs weekday patterns may differ |

### NULL Handling

For new features, `NULL` means "unknown" and is different from `False`:
- `NULL`: Feature value was not captured (old messages before backfill)
- `False`: Feature was checked and not present
- `True`: Feature was checked and present

XGBoost handles `NULL` (NaN) natively and learns optimal decision paths for missing values.

### Feature Extraction from raw_message

Existing messages can have features extracted from `raw_message` JSON:

```sql
-- Example: Extract has_video from raw_message
UPDATE tg_message_log
SET has_video = (raw_message ? 'animation' OR raw_message ? 'video')
WHERE raw_message IS NOT NULL AND has_video IS NULL;

-- Example: Extract forwarded_from_channel
UPDATE tg_message_log
SET forwarded_from_channel = (raw_message->'forward_from_chat'->>'type' = 'channel')
WHERE raw_message ? 'forward_from_chat' AND forwarded_from_channel IS NULL;
```

## Training Data Strategies

### Hypothesis: Closed Groups as Training Data

For invite-only/private groups:
- All members have been manually approved
- Messages are inherently "not spam"
- Can be used as high-quality negative training examples

```sql
-- Bulk mark all messages from a closed group as verified non-spam
UPDATE tg_message_log
SET is_spam = false, manually_verified = true
WHERE chat_id = <closed_group_chat_id>
  AND manually_verified = false;
```

### Hypothesis: High-Confidence Auto-Labeling

Messages with very high/low prediction probabilities that match their current label can be considered reliable training data:

- `spam_prediction_probability > 0.98` AND `is_spam = true` → Reliable spam
- `spam_prediction_probability < 0.02` AND `is_spam = false` → Reliable non-spam

### SQL Patterns for Data Analysis

```sql
-- Find potential false positives (deleted but low spam probability)
SELECT message_content, spam_prediction_probability, user_id, chat_id
FROM tg_message_log
WHERE is_spam = true
  AND spam_prediction_probability < 0.85
  AND manually_verified = false
ORDER BY spam_prediction_probability ASC;

-- Find potential false negatives (not marked spam but high probability)
SELECT message_content, spam_prediction_probability, user_id, chat_id
FROM tg_message_log
WHERE is_spam = false
  AND spam_prediction_probability > 0.7
  AND manually_verified = false
ORDER BY spam_prediction_probability DESC;

-- Count messages by verification status
SELECT
    is_spam,
    manually_verified,
    COUNT(*) as count
FROM tg_message_log
GROUP BY is_spam, manually_verified;
```

## Configuration

### Chat Config Options

```json
{
    "agressive_antispam": true,    // Enable language/file filters
    "ai_spam_check_enabled": true, // Enable ML spam detection
    "ai_spamcheck_enabled": true   // Enable new ML model
}
```

### Environment Variables

- `ENV_BOT_ADMIN_ID` - Super admin user ID (can use /verify_user, /unspam, etc.)

## Monitoring

### Log Format for Spam Detection

```
╔═ AI-Spamcheck
║ Probability  : ⚠️ 0.85432  (del≥0.8, mute≥0.95)
╚═ 📝 Content   : Message text here...
            ↳ User: [123] - Name - @username
            ↳ Chat: Chat Name (chat_id)
            ↳ Action: delete
            ↳ Engine: raw
            ↳ Msg-log-ID: 12345
```

### Log Format for Verified Users

```
╔═ AI-Spamcheck (VERIFIED USER)
║ Probability  : ✅ 0.85432  (del≥0.8, mute≥0.95)
╚═ 📝 Content   : Message text here...
            ↳ User: [123] - Name - @username
            ↳ Chat: Chat Name (chat_id)
            ↳ Action: verified_bypass (no action taken)
```

## Model Training

### Training Script

The primary training script is `src/cron/antispam_ml_optimized.py`:

```bash
# Run training locally
python3 src/cron/antispam_ml_optimized.py

# Train and deploy to server
./src/cron/antispam_ml_train_and_push.sh
```

### Training Pipeline

1. **Data Fetching**: Queries messages with embeddings that are either manually verified or have extreme prediction probabilities (>0.99 spam, <0.01 not spam)
2. **Feature Extraction**: Extracts 20 scalar features + 3072d embeddings per message
3. **Preprocessing**:
   - SimpleImputer fills missing values with mean
   - StandardScaler normalizes all features
4. **Training**: XGBoost classifier with 80/20 train/test split
5. **Evaluation**: Logs accuracy and misclassified messages for review
6. **Model Export**: Saves to `ml_models/xgb_spam_model.joblib` and `ml_models/scaler.joblib`

### Model Parameters

```python
XGBClassifier(
    n_estimators=100,
    max_depth=6,
    learning_rate=0.1,
    n_jobs=-1,
    random_state=42,
    eval_metric='logloss'
)
```

### Feature Design Decisions

| Feature | Decision | Rationale |
|---------|----------|-----------|
| `log10(user_id)` | **ADDED** | Telegram user IDs are sequential - higher ID = newer account. Analysis showed accounts <3 years old have 20% spam rate, accounts <2 months have 98% spam rate. Log transform used for scale normalization. Model retrains regularly, so adapts to new ID ranges automatically. |
| `user_id` (raw) | Removed | Raw ID causes overfitting - model memorizes specific users instead of learning generalizable patterns |
| `reply_to_message_id` (raw) | Changed to binary `is_reply` | Raw message ID has no semantic meaning - only matters whether it's a reply or not |

### Training Data Quality

For best results, ensure balanced training data:

```sql
-- Check class balance
SELECT is_spam, COUNT(*)
FROM tg_message_log
WHERE manually_verified = true
   OR spam_prediction_probability > 0.99
   OR spam_prediction_probability < 0.01
GROUP BY is_spam;
```

Aim for roughly balanced classes. If imbalanced, consider:
- Adding more manually verified examples of the minority class
- Adjusting prediction probability thresholds
- Using class weights in the model
