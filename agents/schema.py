"""Validation of the JSON response contract returned by AI player agents.

This module is the only place that decides whether an agent response is
well-formed. Semantic legality of the values (e.g. targeting a dead player)
is checked later by engine/actions.py.
"""

import json

from engine.models import ActionType


class ResponseParseError(Exception):
    """Raised when an agent response does not match the expected contract."""


_TOP_KEYS = {"message", "action"}
_ACTION_KEYS = {"type", "target"}
_VALID_ACTION_TYPES = {action_type.value for action_type in ActionType}


def parse_response(raw_text: str) -> dict:
    """Parse and validate the raw text returned by an agent.

    Returns the parsed dict unchanged when it matches the contract, otherwise
    raises ResponseParseError.
    """
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ResponseParseError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ResponseParseError("top-level value must be a JSON object")
    if set(data) != _TOP_KEYS:
        raise ResponseParseError(f"expected exactly the keys {sorted(_TOP_KEYS)}")

    message = data["message"]
    if message is not None and not isinstance(message, str):
        raise ResponseParseError("'message' must be a string or null")

    action = data["action"]
    if action is None:
        return data
    if not isinstance(action, dict):
        raise ResponseParseError("'action' must be an object or null")
    if set(action) != _ACTION_KEYS:
        raise ResponseParseError(f"'action' must have exactly the keys {sorted(_ACTION_KEYS)}")
    if not isinstance(action["type"], str) or action["type"] not in _VALID_ACTION_TYPES:
        raise ResponseParseError(f"unknown action type: {action['type']!r}")
    target = action["target"]
    if target is not None and not isinstance(target, str):
        raise ResponseParseError("'action.target' must be a string or null")

    return data
