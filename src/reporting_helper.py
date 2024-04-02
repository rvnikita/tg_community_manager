from sqlalchemy import func
from datetime import datetime

import src.db_helper as db_helper
import src.logging_helper as logging


logger = logging.get_logger()

async def add_report(reported_user_id, reporting_user_id, reported_message_id, chat_id, report_power):
    try:
        with db_helper.session_scope() as db_session:
            report = db_helper.Report(
                reported_user_id=reported_user_id,
                reporting_user_id=reporting_user_id,
                reported_message_id=reported_message_id,
                chat_id=chat_id,
                report_power=report_power
            )
            db_session.add(report)
            db_session.commit()
            return True
    except Exception as e:
        logger.error(f"Error adding report: {e}")
        return False

async def log_spam_report(user_id, user_nickname, user_current_rating, chat_id, message_content, action_type, admin_id, admin_nickname, reason_for_action):
    try:
        with db_helper.session_scope() as db_session:
            spam_report_log = db_helper.SpamReportLog(
                message_content=message_content,
                user_id=user_id,
                user_nickname=user_nickname,
                user_current_rating=user_current_rating,
                chat_id=chat_id,
                message_timestamp=datetime.now(),
                action_type=action_type,
                admin_id=admin_id,
                admin_nickname=admin_nickname,
                reason_for_action=reason_for_action
            )
            db_session.add(spam_report_log)
            db_session.commit()

            #super detailed log
            logger.info(f"User {user_nickname} ({user_id}) in chat {chat_id} was spam logged by {admin_nickname} ({admin_id}) for {reason_for_action}. Message content: {message_content}")

            return True
    except Exception as e:
        logger.error(f"Error logging spam report: {e}")
        return False

async def calculate_cumulative_report_power(chat_id, reported_user_id):
    try:
        with db_helper.session_scope() as db_session:
            cumulative_report_power = db_session.query(
                func.sum(db_helper.Report.report_power)
            ).filter(
                db_helper.Report.chat_id == chat_id,
                db_helper.Report.reported_user_id == reported_user_id
            ).scalar() or 0
            return cumulative_report_power
    except Exception as e:
        logger.error(f"Error calculating cumulative report power: {e}")
        return None

async def check_existing_report(chat_id, reported_user_id, reporting_user_id):
    try:
        with db_helper.session_scope() as db_session:
            existing_report = db_session.query(db_helper.Report).filter(
                db_helper.Report.chat_id == chat_id,
                db_helper.Report.reported_user_id == reported_user_id,
                db_helper.Report.reporting_user_id == reporting_user_id
            ).first()
            return existing_report is not None
    except Exception as e:
        logger.error(f"Error calculating cumulative report power: {e}")
        return None

async def get_reporting_users(chat_id, reported_user_id):
    try:
        with db_helper.session_scope() as db_session:
            reporting_user_ids = db_session.query(db_helper.Report.reporting_user_id).filter(
                db_helper.Report.reported_user_id == reported_user_id,
                db_helper.Report.chat_id == chat_id
            ).distinct().all()
            return [user_id[0] for user_id in reporting_user_ids]
    except Exception as e:
        logger.error(f"Error getting reporting users: {e}")
        return []