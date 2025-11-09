"""
Trigger-Action Chain System

This module provides a flexible trigger-action system for custom per-chat message handling.
Chains consist of triggers (conditions) and actions (responses) that execute in sequence.

Architecture:
- Triggers evaluate message conditions (regex, LLM boolean checks, etc.)
- Actions perform operations when triggers match (reply, info, etc.)
- All configuration is stored in JSON format for flexibility
- Chains are chat-specific and execute in priority order

Trigger Types:
- regex: Match message text against regex pattern
- llm_boolean: Use LLM to evaluate message against custom criteria with structured output

Action Types:
- reply: Send a reply message
- info: Apply /info command to show user info
- spam: Mark user as spammer, globally ban, and delete their messages
"""

import re
import json
import logging
from typing import Dict, Any
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from src.helpers.db_helper import Session, Trigger_Action_Chain, Chain_Trigger, Chain_Action, Chain_Execution_Log
from src.helpers.db_helper import Message_Log
from src.helpers.openai_helper import call_openai_structured
from src.helpers.user_helper import get_user_info_text
from src.helpers import chat_helper, message_helper

logger = logging.getLogger(__name__)


# ============================================================================
# Base Classes
# ============================================================================

class BaseTrigger:
    """Base class for all trigger types"""

    def __init__(self, trigger_id: int, config: Dict[str, Any], order: int):
        self.trigger_id = trigger_id
        self.config = config
        self.order = order

    async def evaluate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Evaluate if trigger condition is met. Returns True if matched."""
        raise NotImplementedError()


class BaseAction:
    """Base class for all action types"""

    def __init__(self, action_id: int, config: Dict[str, Any], order: int):
        self.action_id = action_id
        self.config = config
        self.order = order

    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Execute the action. Returns True if successful."""
        raise NotImplementedError()


# ============================================================================
# Trigger Implementations
# ============================================================================

class RegexTrigger(BaseTrigger):
    """Trigger that matches message text against a regex pattern

    Config format:
    {
        "pattern": "regex pattern string",
        "flags": ["IGNORECASE", "MULTILINE", ...]  # optional, list of flag names
    }
    """

    def __init__(self, trigger_id: int, config: Dict[str, Any], order: int):
        super().__init__(trigger_id, config, order)

        pattern = config.get("pattern")
        if not pattern:
            raise ValueError("RegexTrigger requires 'pattern' in config")

        # Parse flags from config
        flags = 0
        flag_names = config.get("flags", [])
        for flag_name in flag_names:
            if hasattr(re, flag_name):
                flags |= getattr(re, flag_name)

        self.regex = re.compile(pattern, flags)

    async def evaluate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if message text matches regex pattern"""
        if not update.message or not update.message.text:
            return False

        match = self.regex.search(update.message.text)
        logger.debug(f"RegexTrigger {self.trigger_id}: pattern={self.regex.pattern}, matched={bool(match)}")
        return bool(match)


class LLMBooleanTrigger(BaseTrigger):
    """Trigger that uses LLM to evaluate message against custom criteria

    Config format:
    {
        "prompt": "Custom prompt for LLM evaluation",
        "schema": {
            "type": "object",
            "properties": {
                "matches": {
                    "type": "boolean",
                    "description": "True if message matches criteria"
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of decision"
                }
            },
            "required": ["matches", "reason"],
            "additionalProperties": false
        }
    }
    """

    def __init__(self, trigger_id: int, config: Dict[str, Any], order: int):
        super().__init__(trigger_id, config, order)

        if "prompt" not in config:
            raise ValueError("LLMBooleanTrigger requires 'prompt' in config")
        if "schema" not in config:
            raise ValueError("LLMBooleanTrigger requires 'schema' in config")

        self.prompt = config["prompt"]
        self.schema = config["schema"]

    async def evaluate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Use LLM with structured output to evaluate message"""
        if not update.message or not update.message.text:
            return False

        try:
            # Build full prompt with message text
            full_prompt = f"{self.prompt}\n\nMessage to evaluate: {update.message.text}"

            # Call OpenAI with structured output
            result = await call_openai_structured(
                prompt=full_prompt,
                response_format=self.schema
            )

            # Result is already parsed as dict by call_openai_structured
            if not result:
                logger.warning(f"LLMBooleanTrigger {self.trigger_id}: got None result from OpenAI")
                return False

            matches = result.get("matches", False)
            reason = result.get("reason", "No reason provided")

            logger.info(f"LLMBooleanTrigger {self.trigger_id}: matches={matches}, reason={reason}")
            return matches

        except Exception as e:
            logger.error(f"LLMBooleanTrigger {self.trigger_id} failed: {e}")
            return False


# ============================================================================
# Action Implementations
# ============================================================================

class ReplyAction(BaseAction):
    """Action that sends a reply to the message

    Config format:
    {
        "text": "Reply message text"
    }
    """

    def __init__(self, action_id: int, config: Dict[str, Any], order: int):
        super().__init__(action_id, config, order)

        if "text" not in config:
            raise ValueError("ReplyAction requires 'text' in config")

        self.text = config["text"]

    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Send reply message"""
        try:
            await update.message.reply_text(self.text)
            logger.info(f"ReplyAction {self.action_id}: sent reply")
            return True
        except Exception as e:
            # If reply fails (e.g., message deleted), try sending as regular message
            if "Message to be replied not found" in str(e):
                try:
                    await context.bot.send_message(
                        chat_id=update.message.chat.id,
                        text=self.text
                    )
                    logger.info(f"ReplyAction {self.action_id}: sent as regular message (original deleted)")
                    return True
                except Exception as send_error:
                    logger.error(f"ReplyAction {self.action_id} fallback failed: {send_error}")
                    return False

            logger.error(f"ReplyAction {self.action_id} failed: {e}")
            return False


class InfoAction(BaseAction):
    """Action that applies /info command to show user info

    Config format:
    {} (no specific config needed)
    """

    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Show user info for message author"""
        try:
            user = update.message.from_user
            chat = update.message.chat

            # Get user info text from shared helper
            info_text = await get_user_info_text(user.id, chat.id)

            # Send as reply
            await update.message.reply_text(info_text)
            logger.info(f"InfoAction {self.action_id}: sent user info for user {user.id}")
            return True

        except Exception as e:
            # If reply fails (e.g., message deleted), try sending as regular message
            if "Message to be replied not found" in str(e):
                try:
                    user = update.message.from_user
                    chat = update.message.chat
                    info_text = await get_user_info_text(user.id, chat.id)

                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=info_text
                    )
                    logger.info(f"InfoAction {self.action_id}: sent as regular message (original deleted)")
                    return True
                except Exception as send_error:
                    logger.error(f"InfoAction {self.action_id} fallback failed: {send_error}")
                    return False

            logger.error(f"InfoAction {self.action_id} failed: {e}")
            return False


class SpamAction(BaseAction):
    """Action that marks user as spammer, globally bans them, and deletes their messages

    This action performs the same operations as the /spam command:
    - Globally bans the user
    - Marks all their messages as spam in the database
    - Deletes all their messages from the last 24 hours
    - Deletes the triggering message

    Config format:
    {
        "reason": "Optional custom reason for the ban"
    }
    """

    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Execute spam action on message author"""
        try:
            user = update.message.from_user
            chat_id = update.message.chat.id
            message_id = update.message.message_id
            target_user_id = user.id

            reason = self.config.get("reason", "Automatic spam detection via trigger-action chain")

            # 1. Delete the spam message
            await chat_helper.delete_message(context.bot, chat_id, message_id)
            logger.info(f"SpamAction {self.action_id}: deleted message {message_id}")

            # 2. Globally ban the user
            await chat_helper.ban_user(
                context.bot,
                chat_id,
                target_user_id,
                global_ban=True,
                reason=reason
            )
            logger.info(f"SpamAction {self.action_id}: globally banned user {target_user_id}")

            # 3. Mark all messages from this user as spam
            with Session() as session:
                logs = session.query(Message_Log).filter(
                    Message_Log.user_id == target_user_id
                ).all()
                logs_data = [
                    {"chat_id": log.chat_id, "message_id": log.message_id}
                    for log in logs
                ]

            for log_data in logs_data:
                message_helper.insert_or_update_message_log(
                    chat_id=log_data["chat_id"],
                    message_id=log_data["message_id"],
                    user_id=target_user_id,
                    is_spam=True,
                    manually_verified=True,
                    reason_for_action=reason
                )
            logger.info(f"SpamAction {self.action_id}: marked {len(logs_data)} messages as spam")

            # 4. Delete all messages from the last 24 hours
            cutoff = datetime.now() - timedelta(hours=24)
            with Session() as session:
                recent_logs = session.query(Message_Log).filter(
                    Message_Log.user_id == target_user_id,
                    Message_Log.created_at >= cutoff
                ).all()
                recent_logs_data = [
                    {"chat_id": log.chat_id, "message_id": log.message_id}
                    for log in recent_logs
                ]

            for log_data in recent_logs_data:
                try:
                    await chat_helper.delete_message(context.bot, log_data["chat_id"], log_data["message_id"])
                except Exception as exc:
                    logger.warning(f"SpamAction {self.action_id}: Failed to delete message {log_data['message_id']}: {exc}")

            logger.info(f"SpamAction {self.action_id}: deleted {len(recent_logs_data)} recent messages")
            return True

        except Exception as e:
            logger.error(f"SpamAction {self.action_id} failed: {e}")
            return False


# ============================================================================
# Factory Functions
# ============================================================================

TRIGGER_REGISTRY = {
    "regex": RegexTrigger,
    "llm_boolean": LLMBooleanTrigger,
}

ACTION_REGISTRY = {
    "reply": ReplyAction,
    "info": InfoAction,
    "spam": SpamAction,
}


def create_trigger(trigger: Chain_Trigger) -> BaseTrigger:
    """Create a trigger instance from database model"""
    trigger_class = TRIGGER_REGISTRY.get(trigger.trigger_type)
    if not trigger_class:
        raise ValueError(f"Unknown trigger type: {trigger.trigger_type}")

    return trigger_class(
        trigger_id=trigger.id,
        config=trigger.config,
        order=trigger.order
    )


def create_action(action: Chain_Action) -> BaseAction:
    """Create an action instance from database model"""
    action_class = ACTION_REGISTRY.get(action.action_type)
    if not action_class:
        raise ValueError(f"Unknown action type: {action.action_type}")

    return action_class(
        action_id=action.id,
        config=action.config,
        order=action.order
    )


# ============================================================================
# Chain Execution
# ============================================================================

async def execute_chains_for_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute all enabled trigger-action chains for a message

    This is the main entry point called from message handlers.
    Chains are executed in priority order (lower priority = higher precedence).
    """
    if not update.message or not update.message.chat:
        return

    chat_id = update.message.chat.id
    message_id = update.message.message_id
    user_id = update.message.from_user.id if update.message.from_user else 0

    session = Session()
    try:
        # Get all enabled chains for this chat, ordered by priority
        chains = session.query(Trigger_Action_Chain).filter(
            Trigger_Action_Chain.chat_id == chat_id,
            Trigger_Action_Chain.enabled == True
        ).order_by(Trigger_Action_Chain.priority).all()

        if not chains:
            logger.debug(f"No enabled chains for chat {chat_id}")
            return

        logger.info(f"Processing {len(chains)} chains for message {message_id} in chat {chat_id}")

        for chain in chains:
            await execute_single_chain(chain, update, context, session)

    finally:
        session.close()


async def execute_single_chain(
    chain: Trigger_Action_Chain,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session
) -> None:
    """Execute a single trigger-action chain

    Evaluates all triggers in order. If all triggers match, executes all actions in order.
    Logs execution results to database.
    """
    message_id = update.message.message_id
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id if update.message.from_user else 0

    trigger_results = {}
    actions_executed = []
    success = False
    error_message = None

    try:
        logger.info(f"Executing chain '{chain.name}' (id={chain.id}) for message {message_id}")

        # Load and sort triggers
        triggers = sorted(chain.triggers, key=lambda t: t.order)

        if not triggers:
            logger.warning(f"Chain {chain.id} has no triggers")
            return

        # Evaluate all triggers in order
        all_matched = True
        for trigger_model in triggers:
            try:
                trigger = create_trigger(trigger_model)
                matched = await trigger.evaluate(update, context)

                trigger_results[f"trigger_{trigger.trigger_id}"] = {
                    "type": trigger_model.trigger_type,
                    "matched": matched,
                    "order": trigger.order
                }

                if not matched:
                    all_matched = False
                    logger.info(f"Chain {chain.id}: trigger {trigger.trigger_id} did not match, stopping")
                    break

            except Exception as e:
                logger.error(f"Chain {chain.id}: trigger {trigger_model.id} failed: {e}")
                trigger_results[f"trigger_{trigger_model.id}"] = {
                    "type": trigger_model.trigger_type,
                    "error": str(e)
                }
                all_matched = False
                break

        # If all triggers matched, execute actions
        if all_matched:
            logger.info(f"Chain {chain.id}: all triggers matched, executing actions")

            # Load and sort actions
            actions = sorted(chain.actions, key=lambda a: a.order)

            for action_model in actions:
                try:
                    action = create_action(action_model)
                    action_success = await action.execute(update, context)

                    actions_executed.append({
                        "action_id": action.action_id,
                        "type": action_model.action_type,
                        "success": action_success,
                        "order": action.order
                    })

                except Exception as e:
                    logger.error(f"Chain {chain.id}: action {action_model.id} failed: {e}")
                    actions_executed.append({
                        "action_id": action_model.id,
                        "type": action_model.action_type,
                        "error": str(e)
                    })

            success = True
        else:
            logger.debug(f"Chain {chain.id}: triggers did not match, skipping actions")

    except Exception as e:
        logger.error(f"Chain {chain.id} execution failed: {e}")
        error_message = str(e)
        success = False

    finally:
        # Log execution to database
        try:
            log = Chain_Execution_Log(
                chain_id=chain.id,
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                trigger_results=trigger_results,
                actions_executed=actions_executed if actions_executed else None,
                success=success,
                error_message=error_message
            )
            session.add(log)
            session.commit()
        except Exception as e:
            logger.error(f"Failed to log chain execution: {e}")
            session.rollback()
