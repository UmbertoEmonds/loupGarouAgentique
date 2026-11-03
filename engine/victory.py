from __future__ import annotations

from engine.models import Camp, GameState, Role


def check_victory(state: GameState) -> Camp | None:
    """Return the winning camp, or None if the game goes on.

    Villagers win when no wolf is alive. Wolves win only on strict numeric
    superiority over the other living players (never on parity).
    """
    alive = [p for p in state.players.values() if p.alive]
    alive_wolves = [p for p in alive if p.role == Role.LOUP]
    if not alive_wolves:
        return Camp.VILLAGEOIS
    alive_others = [p for p in alive if p.role != Role.LOUP]
    if len(alive_wolves) > len(alive_others):
        return Camp.LOUPS
    return None
