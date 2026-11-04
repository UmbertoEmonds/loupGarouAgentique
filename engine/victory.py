from __future__ import annotations

from engine.models import Camp, GameState, Role


def check_victory(state: GameState) -> Camp | None:
    """Retourne le camp vainqueur, ou None si la partie continue.

    Les villageois gagnent quand aucun loup n'est vivant. Les loups ne
    gagnent qu'en supériorité numérique stricte sur les autres joueurs
    vivants (jamais à égalité).
    """
    alive = [p for p in state.players.values() if p.alive]
    alive_wolves = [p for p in alive if p.role == Role.LOUP]
    if not alive_wolves:
        return Camp.VILLAGEOIS
    alive_others = [p for p in alive if p.role != Role.LOUP]
    if len(alive_wolves) > len(alive_others):
        return Camp.LOUPS
    return None
