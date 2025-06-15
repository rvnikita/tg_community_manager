# src/spamcheck_helper_raw.py
import os, traceback, numpy as np
from datetime import datetime, timezone
from joblib import load
import src.helpers.db_helper as db_helper
import src.helpers.logging_helper as logging_helper
import src.helpers.openai_helper as openai_helper
import src.helpers.rating_helper as rating_helper

logger = logging_helper.get_logger()

MODEL = load("ml_models/svm_spam_model_raw.joblib")
SCALER = load("ml_models/scaler_raw.joblib")

#TODO:HIGH: We should use amount of spam messages already sent by the user in the chat

# ---------- helpers ----------------------------------------------------------
def _extract_raw_features(raw_msg):
    ce_cnt = 0
    txt_len = 0
    raw_chat_id = 0
    if isinstance(raw_msg, dict):
        for ent in raw_msg.get("entities", []):
            if isinstance(ent, dict) and "custom_emoji_id" in ent:
                ce_cnt += 1
        if isinstance(raw_msg.get("text"), str):
            txt_len = len(raw_msg["text"])
        chat = raw_msg.get("chat")
        if isinstance(chat, dict):
            raw_chat_id = chat.get("id", 0)
    return ce_cnt, txt_len, raw_chat_id


def _name_lens(user_raw, first, last):
    fn = (user_raw or {}).get("first_name") or first or ""
    ln = (user_raw or {}).get("last_name")  or last  or ""
    return len(fn), len(ln)

# ---------- public API -------------------------------------------------------
async def predict_spam(*, user_id, chat_id, message_text, raw_message, embedding=None):
    try:
        if embedding is None:
            embedding = await openai_helper.generate_embedding(message_text)

        with db_helper.session_scope() as s:
            user = s.query(db_helper.User).get(user_id)
            if not user:
                return 0.0
            ce_cnt, txt_len, raw_chat_id = _extract_raw_features(raw_message)
            delta = (datetime.now(timezone.utc) - user.created_at).total_seconds()
            rating = rating_helper.get_rating(user_id, chat_id)
            fn_len, ln_len = _name_lens(user.user_raw, user.first_name, user.last_name)

        feat = np.concatenate((
            embedding,
            np.array([ce_cnt, txt_len, delta, rating, fn_len, ln_len, raw_chat_id], dtype=float)
        ))
        if np.isnan(feat).any():
            return 0.0
        feat = SCALER.transform([feat])
        return float(MODEL.predict_proba(feat)[0][1])

    except Exception:
        logger.error(f"[raw‑spam] {traceback.format_exc()}")
        return 0.0
