from typing import Protocol


class ActionProvider(Protocol):
    """Seam between the engine and whoever decides an action (AI or human).

    Returns a dict describing the action, or None meaning failed/timed out.
    """

    def get_action(self, player_id: str, context: dict) -> dict | None: ...


def request_with_retry(
    provider: ActionProvider,
    player_id: str,
    context: dict,
    attempts: int = 2,
) -> dict | None:
    """Call provider.get_action up to `attempts` times; return the first non-None result."""
    for _ in range(attempts):
        result = provider.get_action(player_id, context)
        if result is not None:
            return result
    return None
