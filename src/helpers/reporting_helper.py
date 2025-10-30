from sqlalchemy import func
from datetime import datetime
import traceback

import src.helpers.db_helper as db_helper
import src.helpers.logging_helper as logging_helper


logger = logging_helper.get_logger()

async def add_report(reported_user_id, reporting_user_id, reported_message_id, chat_id, report_power, reason=None):
    try:
        with db_helper.session_scope() as db_session:
            report = db_helper.Report(
                reported_user_id=reported_user_id,
                reporting_user_id=reporting_user_id,
                reported_message_id=reported_message_id,
                chat_id=chat_id,
                report_power=report_power,
                reason=reason
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

async def set_report_count(chat_id, reported_user_id, admin_user_id, new_count, reason="Adjusting report count"):
    """
    Set the report count for a user to a specific value.

    Args:
        chat_id: The chat ID where the report count is being set
        reported_user_id: The user whose report count is being adjusted
        admin_user_id: The admin performing the adjustment
        new_count: The desired report count
        reason: Reason for the adjustment (for logging)

    Returns:
        tuple: (success: bool, current_count: int, adjustment: int)
    """
    try:
        current_reports = await get_total_reports(chat_id, reported_user_id)
        if current_reports is None:
            logger.error(f"Failed to get current reports for user {reported_user_id} in chat {chat_id}")
            return False, 0, 0

        adjustment = new_count - current_reports

        # Only add a report if there's an actual adjustment needed
        if adjustment != 0:
            # Use 0 as reported_message_id for admin adjustments, and store the reason in the reason field
            success = await add_report(
                reported_user_id=reported_user_id,
                reporting_user_id=admin_user_id,
                reported_message_id=0,  # 0 indicates admin adjustment, not a real message
                chat_id=chat_id,
                report_power=adjustment,
                reason=reason
            )
            if not success:
                return False, current_reports, 0

        return True, current_reports, adjustment
    except Exception as e:
        logger.error(f"Error setting report count: {e}. Traceback: {traceback.format_exc()}")
        return False, 0, 0

async def clear_reports(chat_id, reported_user_id, admin_user_id):
    """
    Clear all reports for a user (set report count to 0).

    Args:
        chat_id: The chat ID where reports are being cleared
        reported_user_id: The user whose reports are being cleared
        admin_user_id: The admin performing the action

    Returns:
        tuple: (success: bool, previous_count: int)
    """
    try:
        success, previous_count, adjustment = await set_report_count(
            chat_id,
            reported_user_id,
            admin_user_id,
            0,
            "Clearing reports with /ur command"
        )
        return success, previous_count
    except Exception as e:
        logger.error(f"Error clearing reports: {e}. Traceback: {traceback.format_exc()}")
        return False, 0