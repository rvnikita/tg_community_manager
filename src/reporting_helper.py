from sqlalchemy import func
from datetime import datetime
import traceback

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
        logger.error(f"Error adding report: {e}. Traceback: {traceback.format_exc()}")
        return False

# Get the total number of reports a user has received
async def get_total_reports(chat_id, reported_user_id):
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
        logger.error(f"Error calculating cumulative report power: {e}. Traceback: {traceback.format_exc()}")
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
        logger.error(f"Error checking for existing report: {e}. Traceback: {traceback.format_exc()}")
        return None

# Get all users who have reported a user (e.g. used to increase rating of users who reported a spammer)
async def get_reporting_users(chat_id, reported_user_id):
    try:
        with db_helper.session_scope() as db_session:
            reporting_user_ids = db_session.query(db_helper.Report.reporting_user_id).filter(
                db_helper.Report.reported_user_id == reported_user_id,
                db_helper.Report.chat_id == chat_id
            ).distinct().all()
            return [user_id[0] for user_id in reporting_user_ids]
    except Exception as e:
        logger.error(f"Error getting reporting users: {e}. Traceback: {traceback.format_exc()}")
        return []