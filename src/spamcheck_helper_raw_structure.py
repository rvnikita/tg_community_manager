# src/spamcheck_helper_raw_structure.py
import os, traceback, numpy as np
from datetime import datetime, timezone
from joblib import load

import src.db_helper as db_helper
import src.logging_helper as logging_helper
import src.openai_helper as openai_helper
import src.rating_helper as rating_helper

logger = logging_helper.get_logger()

MODEL = load("ml_models/svm_spam_model_raw_structure.joblib")
SCALER = load("ml_models/scaler_raw_structure.joblib")
SCHEMA_KEYS = load("ml_models/schema_keys_raw_structure.joblib")


def _extract_raw_features(raw_msg):
    ce_cnt = 0
    txt_len = 0
    raw_chat_id = 0
    if isinstance(raw_msg, dict):
        for ent in raw_msg.get("entities", []):
            if isinstance(ent, dict) and "custom_emoji_id" in ent:
                ce_cnt += 1
        text = raw_msg.get("text")
        if isinstance(text, str):
            txt_len = len(text)
        chat = raw_msg.get("chat")
        if isinstance(chat, dict):
            raw_chat_id = chat.get("id", 0)
    return ce_cnt, txt_len, raw_chat_id


def _name_lens(user_raw, first, last):
    fn = (user_raw or {}).get("first_name") or first or ""
    ln = (user_raw or {}).get("last_name") or last or ""
    return len(fn), len(ln)


def _extract_structure_features(raw_msg):
    feats = []
    for path in SCHEMA_KEYS:
        curr = raw_msg if isinstance(raw_msg, dict) else {}
        for part in path.split("."):
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                curr = None
                break
        feats.append(1.0 if curr is not None else 0.0)
    return np.array(feats, dtype=float)


async def predict_spam(*, user_id, chat_id, message_text, raw_message, embedding=None):
    try:
        if embedding is None:
            embedding = openai_helper.generate_embedding(message_text)

        with db_helper.session_scope() as s:
            user = s.query(db_helper.User).get(user_id)
            if not user:
                return 0.0

            ce_cnt, txt_len, raw_chat_id = _extract_raw_features(raw_message)
            delta = (datetime.now(timezone.utc) - user.created_at).total_seconds()
            rating = rating_helper.get_rating(user_id, chat_id)
            fn_len, ln_len = _name_lens(user.user_raw, user.first_name, user.last_name)
            struct_feats = _extract_structure_features(raw_message)

        emb = np.asarray(embedding, dtype=float)
        base = np.array([
            ce_cnt,
            txt_len,
            delta,
            rating,
            fn_len,
            ln_len,
            raw_chat_id
        ], dtype=float)

        feat = np.concatenate((emb, base, struct_feats))
        if np.isnan(feat).any():
            return 0.0

        feat = SCALER.transform([feat])
        return float(MODEL.predict_proba(feat)[0][1])
    except Exception:
        logger.error(f"[raw-structure-spam] {traceback.format_exc()}")
        return 0.0
