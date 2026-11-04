"""Ce que chaque agent voit de la partie, construit à un seul endroit.

Tous les agents reçoivent la même structure de contexte ; seules changent
les informations réservées à leur rôle. Centraliser la construction ici
garantit qu'un villageois ne peut pas recevoir par accident le salon des
loups : la règle de visibilité n'est écrite qu'une fois, et c'est le
moteur qui la détient (voir le tableau "schéma mémoire par agent" du
document de design).
"""

from __future__ import annotations

from engine.models import GameState, Player, Role


def build_context(
    state: GameState,
    player: Player,
    legal_action_types: list[str],
    wolf_target_tonight: str | None = None,
) -> dict:
    """Construit le contexte envoyé à un agent pour qu'il décide de son action."""
    is_wolf = player.role == Role.LOUP

    context = {
        "phase": state.phase.value,
        "self_role": player.role.value,
        # Un loup connaît ses alliés encore vivants ; personne d'autre.
        "known_wolf_ids": (
            [w.id for w in state.wolves() if w.alive and w.id != player.id] if is_wolf else []
        ),
        "alive_players": [
            {"id": p.id, "pseudo": p.pseudo} for p in state.players.values() if p.alive
        ],
        "main_room_log": state.main_room_log,
        # Seuls les loups voient leur salon privé.
        "wolf_room_log": state.wolf_room_log if is_wolf else None,
        "legal_action_types": legal_action_types,
    }

    # Information réservée à la sorcière, la nuit : qui les loups ont désigné.
    if wolf_target_tonight is not None:
        context["wolf_target_tonight"] = wolf_target_tonight

    return context
