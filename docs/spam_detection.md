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

### Training Data Sources

Messages are used for training based on these criteria:

```sql
-- Training data selection (from antispam_ml_raw.py)
WHERE manually_verified = true
   OR (spam_prediction_probability > 0.98 AND is_spam = true)
   OR (spam_prediction_probability < 0.02 AND is_spam = false)
```

### Model Types

1. **Raw Text Model** (`spamcheck_helper_raw.py`)
   - Direct text classification
   - Uses text embeddings

2. **Structured Features Model** (`spamcheck_helper_raw_structure.py`)
   - Linguistic feature extraction
   - Combines structural features with embeddings

3. **Combined Model** (`spamcheck_helper.py`)
   - Uses both text and image description embeddings
   - Primary model for spam detection

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
| `is_spam` | Whether message is classified as spam |
| `manually_verified` | Whether classification was manually verified |
| `spam_prediction_probability` | ML model's spam probability (0-1) |
| `reason_for_action` | Human-readable reason for classification |

## ML Features

### Feature List

The spam detection model uses the following features:

| Feature | Type | Description |
|---------|------|-------------|
| `embedding` | Vector (1536d) | OpenAI text embedding of message content |
| `image_description_embedding` | Vector (1536d) | OpenAI embedding of image description (if image present) |
| `user_current_rating` | Integer | User's rating in the chat |
| `time_difference` | Float | Seconds since user joined the chat |
| `chat_id` | Integer | Chat ID (different chats have different spam norms) |
| `message_length` | Integer | Length of message text |
| `spam_count` | Integer | User's previous spam count |
| `not_spam_count` | Integer | User's previous non-spam count |
| `is_forwarded` | Boolean | Whether message is forwarded |
| `reply_to_message_id` | Integer | ID of replied message (0 if not a reply) |
| `has_telegram_nick` | Boolean | Whether message contains @username |
| `has_image` | Boolean | Whether message has an analyzed image |
| `has_video` | Boolean | Whether message has video or animation/GIF |
| `has_document` | Boolean | Whether message has document attachment |
| `has_photo` | Boolean | Whether message has photo |
| `forwarded_from_channel` | Boolean | Whether forwarded from a channel (vs user/group) |
| `has_link` | Boolean | Whether message contains URL links |
| `entity_count` | Integer | Number of entities (links, mentions, etc.) |

### New Features (2025-01)

The following features were added to improve detection of video/media spam:

| Feature | Spam Signal | Why |
|---------|-------------|-----|
| `has_video` | HIGH | Porn/scam spam often uses video content |
| `has_document` | MEDIUM | Document attachments can be malicious (APK, etc.) |
| `has_photo` | LOW | Photos are common but less indicative alone |
| `forwarded_from_channel` | HIGH | Channel forwards are higher risk than user forwards |
| `has_link` | MEDIUM | Links often indicate promotional spam |
| `entity_count` | MEDIUM | Many entities (links, mentions) = suspicious |

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
