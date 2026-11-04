"""Validation du contrat de réponse JSON renvoyé par les agents IA joueurs.

Ce module est le seul endroit qui décide si une réponse d'agent est bien
formée. La légalité sémantique des valeurs (ex: cibler un joueur mort)
est vérifiée plus tard par engine/actions.py.
"""

import json

from engine.models import ActionType


class ResponseParseError(Exception):
    """Levée quand la réponse d'un agent ne correspond pas au contrat attendu."""


_TOP_KEYS = {"message", "action"}
_ACTION_KEYS = {"type", "target"}
_VALID_ACTION_TYPES = {action_type.value for action_type in ActionType}


def parse_response(raw_text: str) -> dict:
    """Parse et valide le texte brut renvoyé par un agent.

    Retourne le dict analysé inchangé quand il correspond au contrat,
    sinon lève ResponseParseError.
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
