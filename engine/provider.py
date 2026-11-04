from typing import Protocol


class ActionProvider(Protocol):
    """Point de couture entre le moteur et qui décide d'une action (IA ou humain).

    Retourne un dict décrivant l'action, ou None en cas d'échec/timeout.
    """

    def get_action(self, player_id: str, context: dict) -> dict | None: ...


def request_with_retry(
    provider: ActionProvider,
    player_id: str,
    context: dict,
    attempts: int = 2,
) -> dict | None:
    """Appelle provider.get_action jusqu'à `attempts` fois ; retourne le premier résultat non None."""
    for _ in range(attempts):
        result = provider.get_action(player_id, context)
        if result is not None:
            return result
    return None
