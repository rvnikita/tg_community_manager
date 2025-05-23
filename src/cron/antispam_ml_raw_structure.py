#!/usr/bin/env python
import asyncio
import traceback
from datetime import datetime, timezone

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.svm import SVC
from joblib import dump

from sqlalchemy import or_, and_

import src.db_helper as db_helper
import src.logging_helper as logging_helper
import src.rating_helper as rating_helper

logger = logging_helper.get_logger()


def collect_all_keys(messages):
    keys = set()

    def recurse(obj, prefix):
        if isinstance(obj, dict):
            for k, v in obj.items():
                path = f"{prefix}.{k}" if prefix else k
                keys.add(path)
                recurse(v, path)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item, prefix)

    for msg in messages:
        recurse(msg, "")
    return sorted(keys)


def extract_structure_features(raw_msg, schema_keys):
    features = []
    for path in schema_keys:
        curr = raw_msg if isinstance(raw_msg, dict) else {}
        for part in path.split("."):
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                curr = None
                break
        features.append(1.0 if curr is not None else 0.0)
    return np.array(features, dtype=float)


def extract_raw_features(raw_msg):
    custom_emoji_count = 0
    raw_text_length = 0
    raw_chat_id = 0
    if isinstance(raw_msg, dict):
        entities = raw_msg.get("entities")
        if isinstance(entities, list):
            for entity in entities:
                if isinstance(entity, dict) and "custom_emoji_id" in entity:
                    custom_emoji_count += 1
        text = raw_msg.get("text")
        if isinstance(text, str):
            raw_text_length = len(text)
        chat_obj = raw_msg.get("chat")
        if isinstance(chat_obj, dict):
            raw_chat_id = chat_obj.get("id", 0)
    return custom_emoji_count, raw_text_length, raw_chat_id


def extract_user_name_lengths(user_raw, fallback_first_name, fallback_last_name):
    first = fallback_first_name
    last = fallback_last_name
    if isinstance(user_raw, dict):
        first = user_raw.get("first_name") or first
        last = user_raw.get("last_name") or last
    return len(first or ""), len(last or "")


async def train_spam_classifier_raw_structure():
    try:
        with db_helper.session_scope() as session:
            logger.info("Fetching messages for structured-raw training...")
            query = (
                session.query(
                    db_helper.Message_Log.id,
                    db_helper.Message_Log.embedding,
                    db_helper.Message_Log.raw_message,
                    db_helper.Message_Log.is_spam,
                    db_helper.Message_Log.user_id,
                    db_helper.Message_Log.chat_id,
                    db_helper.Message_Log.spam_prediction_probability,
                    db_helper.User.created_at.label("user_created_at"),
                    db_helper.User.first_name,
                    db_helper.User.last_name,
                    db_helper.User.user_raw
                )
                .join(db_helper.User, db_helper.User.id == db_helper.Message_Log.user_id)
                .filter(
                    db_helper.Message_Log.embedding != None,
                    db_helper.Message_Log.raw_message != None,
                    or_(
                        db_helper.Message_Log.manually_verified == True,
                        and_(db_helper.Message_Log.spam_prediction_probability > 0.98, db_helper.Message_Log.is_spam == True),
                        and_(db_helper.Message_Log.spam_prediction_probability < 0.02, db_helper.Message_Log.is_spam == False)
                    )
                )
                .order_by(db_helper.Message_Log.id.desc())
            )
            msgs = query.all()
            logger.info(f"Fetched {len(msgs)} messages.")
            if not msgs:
                logger.info("No messages to process.")
                return None

            raw_messages = [m.raw_message for m in msgs if isinstance(m.raw_message, dict)]
            schema_keys = collect_all_keys(raw_messages)

            features = []
            labels = []
            raw_info = []

            now = datetime.now(timezone.utc)
            for m in msgs:
                delta = (now - m.user_created_at).total_seconds()
                custom_count, text_len, chat_id = extract_raw_features(m.raw_message)
                first_len, last_len = extract_user_name_lengths(m.user_raw, m.first_name, m.last_name)
                rating = rating_helper.get_rating(m.user_id, m.chat_id)

                emb = np.asarray(m.embedding, dtype=float)
                base = np.array([
                    custom_count,
                    text_len,
                    delta,
                    rating,
                    first_len,
                    last_len,
                    chat_id
                ], dtype=float)

                struct = extract_structure_features(m.raw_message, schema_keys)
                vec = np.concatenate((emb, base, struct))

                features.append(vec)
                labels.append(m.is_spam)
                raw_info.append({
                    "message_id": m.id,
                    "raw_text": m.raw_message.get("text") if isinstance(m.raw_message, dict) else None,
                    "feature_length": vec.shape[0]
                })

            X = np.vstack(features)
            y = np.array(labels, dtype=bool)

            imputer = SimpleImputer(strategy="mean")
            X = imputer.fit_transform(X)

            uniq, counts = np.unique(y, return_counts=True)
            logger.info(f"Class distribution: {dict(zip(uniq, counts))}")

            X_train, X_test, y_train, y_test, info_train, info_test = train_test_split(
                X, y, raw_info, test_size=0.1, stratify=y
            )

            scaler = StandardScaler().fit(X_train)
            X_train = scaler.transform(X_train)
            X_test = scaler.transform(X_test)

            model = SVC(kernel="rbf", probability=True, C=1.0, gamma="scale")
            model.fit(X_train, y_train)

            acc = model.score(X_test, y_test)
            logger.info(f"Structured-raw model accuracy: {acc}")

            dump(model, "ml_models/svm_spam_model_raw_structure.joblib")
            dump(scaler, "ml_models/scaler_raw_structure.joblib")
            dump(schema_keys, "ml_models/schema_keys_raw_structure.joblib")

            probs = model.predict_proba(X_test)[:, 1]
            preds = model.predict(X_test)
            logger.info("Misclassified samples:")
            for p, t, info in zip(preds, y_test, info_test):
                if p != t:
                    logger.info(
                        f"ID {info['message_id']} pred={p} true={t} prob={probs[info_test.index(info)]:.4f}"
                    )

            return model

    except Exception as e:
        logger.error(f"Error training structured spam classifier: {e}\n{traceback.format_exc()}")
        return None


if __name__ == "__main__":
    asyncio.run(train_spam_classifier_raw_structure())
