# Trigger-Action Chain System

The trigger-action chain system provides flexible, customizable message handling for Telegram chats without requiring code changes for each new scenario.

## Overview

Chains consist of:
- **Triggers**: Conditions that evaluate messages (regex, LLM boolean checks, etc.)
- **Actions**: Operations to perform when triggers match (reply, show info, etc.)

All configuration is stored in JSON format, making the system easily extensible.

## Architecture

### Database Schema

**Trigger_Action_Chain**
- Main chain entity with priority and enabled status
- Multiple chains can exist per chat
- Chains execute in priority order (lower number = higher priority)

**Chain_Trigger**
- Evaluates message conditions
- `trigger_type`: Type identifier (regex, llm_boolean, etc.)
- `config`: JSON field containing all trigger configuration
- `order`: Execution order within chain

**Chain_Action**
- Performs operations when triggers match
- `action_type`: Type identifier (reply, info, etc.)
- `config`: JSON field containing all action configuration
- `order`: Execution order within chain

**Chain_Execution_Log**
- Audit trail of chain executions
- Stores trigger results and actions executed
- Useful for debugging and monitoring

### Execution Flow

1. Message arrives in chat
2. Load all enabled chains for that chat (by priority)
3. For each chain:
   - Evaluate triggers in order
   - If ALL triggers match → execute all actions in order
   - If ANY trigger fails → skip actions
4. Log execution results to database

### Cost Optimization

Triggers execute in order, allowing optimization:
- Place fast checks (regex) before expensive checks (LLM)
- Chain stops at first non-matching trigger
- Saves API costs for LLM-based triggers

## Trigger Types

### RegexTrigger

Matches message text against a regex pattern.

**Config format:**
```json
{
    "pattern": "regex pattern string",
    "flags": ["IGNORECASE", "MULTILINE"]  // optional
}
```

**Example:**
```json
{
    "pattern": "продам|куплю|обменяю",
    "flags": ["IGNORECASE"]
}
```

### LLMBooleanTrigger

Uses OpenAI with structured output to evaluate messages against custom criteria.

**Config format:**
```json
{
    "prompt": "Custom evaluation prompt",
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
```

**Example:**
```json
{
    "prompt": "Does this message contain any attempt to sell goods or services?",
    "schema": {
        "type": "object",
        "properties": {
            "matches": {"type": "boolean", "description": "True if selling"},
            "reason": {"type": "string", "description": "Why classified as selling"}
        },
        "required": ["matches", "reason"],
        "additionalProperties": false
    }
}
```

## Action Types

### ReplyAction

Sends a reply message to the triggering message.

**Config format:**
```json
{
    "text": "Reply message text"
}
```

**Example:**
```json
{
    "text": "⚠️ This chat is for cultural discussions only. Please use appropriate channels for commercial posts."
}
```

### InfoAction

Shows user information (same as /info command) for the message author.

**Config format:**
```json
{}
```

No configuration needed. Automatically shows:
- Username and full name
- Account age
- Rating in the chat
- Message counts

## Usage Examples

### Example 1: Simple Keyword Detection

Detect "продам" keyword and show user info.

**Create chain:**
```python
from src.helpers.db_helper import Session, Trigger_Action_Chain, Chain_Trigger, Chain_Action

session = Session()

# Create chain
chain = Trigger_Action_Chain(
    chat_id=-1001688952630,
    name="Sale keyword detection",
    description="Detect 'продам' and show user info",
    priority=100,
    enabled=True
)
session.add(chain)
session.flush()

# Add trigger
trigger = Chain_Trigger(
    chain_id=chain.id,
    trigger_type="regex",
    order=0,
    config={
        "pattern": "продам",
        "flags": ["IGNORECASE"]
    }
)
session.add(trigger)

# Add action
action = Chain_Action(
    chain_id=chain.id,
    action_type="info",
    order=0,
    config={}
)
session.add(action)

session.commit()
session.close()
```

### Example 2: Multi-Trigger Chain with LLM

Use regex for fast filtering, then LLM for accurate detection.

**Create chain:**
```python
# Create chain
chain = Trigger_Action_Chain(
    chat_id=-1001688952630,
    name="Sale detection (optimized)",
    description="Regex + LLM for accurate sale detection",
    priority=100,
    enabled=True
)
session.add(chain)
session.flush()

# Trigger 1: Fast regex pre-filter
trigger1 = Chain_Trigger(
    chain_id=chain.id,
    trigger_type="regex",
    order=0,  # runs first
    config={
        "pattern": "продам|продаю|продаётся|купить|покупаю|обмен",
        "flags": ["IGNORECASE"]
    }
)
session.add(trigger1)

# Trigger 2: Accurate LLM check (only if regex matched)
trigger2 = Chain_Trigger(
    chain_id=chain.id,
    trigger_type="llm_boolean",
    order=1,  # runs second
    config={
        "prompt": "Is this message attempting to sell, buy, or exchange goods/services/tickets?",
        "schema": {
            "type": "object",
            "properties": {
                "matches": {
                    "type": "boolean",
                    "description": "True if commercial activity detected"
                },
                "reason": {
                    "type": "string",
                    "description": "Explanation of classification"
                }
            },
            "required": ["matches", "reason"],
            "additionalProperties": false
        }
    }
)
session.add(trigger2)

# Action 1: Reply with warning
action1 = Chain_Action(
    chain_id=chain.id,
    action_type="reply",
    order=0,
    config={
        "text": "⚠️ Commercial posts are not allowed in this chat."
    }
)
session.add(action1)

# Action 2: Show user info
action2 = Chain_Action(
    chain_id=chain.id,
    action_type="info",
    order=1,
    config={}
)
session.add(action2)

session.commit()
session.close()
```

## Managing Chains

### Enable/Disable Chain

```python
session = Session()
chain = session.query(Trigger_Action_Chain).filter_by(id=CHAIN_ID).first()
chain.enabled = False  # or True
session.commit()
session.close()
```

### Change Priority

Lower number = higher priority (executes first).

```python
session = Session()
chain = session.query(Trigger_Action_Chain).filter_by(id=CHAIN_ID).first()
chain.priority = 50  # higher priority
session.commit()
session.close()
```

### Delete Chain

Cascades to delete all triggers, actions, and logs.

```python
session = Session()
chain = session.query(Trigger_Action_Chain).filter_by(id=CHAIN_ID).first()
session.delete(chain)
session.commit()
session.close()
```

## Adding New Trigger/Action Types

### Adding a New Trigger

1. Create trigger class in `trigger_action_helper.py`:

```python
class CustomTrigger(BaseTrigger):
    """Your trigger description

    Config format:
    {
        "param1": "value",
        "param2": 123
    }
    """

    def __init__(self, trigger_id: int, config: Dict[str, Any], order: int):
        super().__init__(trigger_id, config, order)
        # Validate and parse config
        self.param1 = config.get("param1")
        if not self.param1:
            raise ValueError("CustomTrigger requires 'param1' in config")

    async def evaluate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Evaluate trigger condition"""
        # Your logic here
        return True  # or False
```

2. Register in `TRIGGER_REGISTRY`:

```python
TRIGGER_REGISTRY = {
    "regex": RegexTrigger,
    "llm_boolean": LLMBooleanTrigger,
    "custom": CustomTrigger,  # add here
}
```

3. Use in database with `trigger_type="custom"` and appropriate config JSON.

### Adding a New Action

1. Create action class in `trigger_action_helper.py`:

```python
class CustomAction(BaseAction):
    """Your action description

    Config format:
    {
        "param1": "value"
    }
    """

    def __init__(self, action_id: int, config: Dict[str, Any], order: int):
        super().__init__(action_id, config, order)
        self.param1 = config.get("param1")

    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Execute the action"""
        try:
            # Your logic here
            return True  # success
        except Exception as e:
            logger.error(f"CustomAction {self.action_id} failed: {e}")
            return False
```

2. Register in `ACTION_REGISTRY`:

```python
ACTION_REGISTRY = {
    "reply": ReplyAction,
    "info": InfoAction,
    "custom": CustomAction,  # add here
}
```

3. Use in database with `action_type="custom"` and appropriate config JSON.

## Debugging

### View Execution Logs

```python
from src.helpers.db_helper import Session, Chain_Execution_Log

session = Session()
logs = session.query(Chain_Execution_Log).filter_by(
    chain_id=CHAIN_ID
).order_by(Chain_Execution_Log.triggered_at.desc()).limit(10).all()

for log in logs:
    print(f"Chain: {log.chain_id}")
    print(f"Message: {log.message_id}")
    print(f"Success: {log.success}")
    print(f"Triggers: {log.trigger_results}")
    print(f"Actions: {log.actions_executed}")
    if log.error_message:
        print(f"Error: {log.error_message}")
    print("---")

session.close()
```

### Check Enabled Chains for Chat

```python
from src.helpers.db_helper import Session, Trigger_Action_Chain

session = Session()
chains = session.query(Trigger_Action_Chain).filter_by(
    chat_id=-1001688952630,
    enabled=True
).order_by(Trigger_Action_Chain.priority).all()

for chain in chains:
    print(f"[{chain.priority}] {chain.name}")
    print(f"  Triggers: {len(chain.triggers)}")
    print(f"  Actions: {len(chain.actions)}")

session.close()
```

## Best Practices

1. **Optimize trigger order**: Place fast checks (regex) before expensive checks (LLM)
2. **Use descriptive names**: Make chains easy to identify and manage
3. **Set appropriate priorities**: Critical chains should have lower priority numbers
4. **Monitor execution logs**: Check for errors and unexpected behavior
5. **Test before enabling**: Create chains as disabled, test thoroughly, then enable
6. **Document custom triggers/actions**: Add clear docstrings with config format examples
7. **Validate config in __init__**: Fail fast if configuration is invalid

## Migration

The database migration creates all necessary tables:

```bash
source venv/bin/activate
source config/setenv.sh
alembic upgrade head
```

Migration file: `alembic/versions/f5d5db155a1a_add_trigger_action_chain_tables_with_.py`
