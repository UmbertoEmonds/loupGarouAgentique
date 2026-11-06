from __future__ import annotations

import random

from engine.models import GameState, Phase, Player, Role

PRENOMS = ["Ines", "Amaury", "Sarah", "Baptiste", "Benji"]
PERSONNALITES = ["mauvais_joueur", "stratege", "impatient", "paranoiaque", "manipulateur"]
ROLE_COUNTS = {Role.LOUP: 2, Role.SORCIERE: 1, Role.VILLAGEOIS: 3}


def new_game(
    human_pseudo: str,
    rng: random.Random | None = None,
    human_role: Role | None = None,
) -> GameState:
    """Crée la partie. `human_role` impose le rôle de l'humain (tiré au sort si None) ;
    les rôles restants sont répartis au hasard entre les IA."""
    rng = rng or random.Random()

    roles = [role for role, count in ROLE_COUNTS.items() for _ in range(count)]
    rng.shuffle(roles)
    if human_role is not None:
        roles.remove(human_role)
        roles.insert(0, human_role)

    pairings = list(zip(PRENOMS, PERSONNALITES))
    rng.shuffle(pairings)

    players: dict[str, Player] = {
        "human": Player(
            id="human",
            pseudo=human_pseudo,
            is_human=True,
            role=roles[0],
            personality=None,
        ),
    }
    for i, (pseudo, personality) in enumerate(pairings, start=1):
        pid = f"ia_{i}"
        players[pid] = Player(
            id=pid,
            pseudo=pseudo,
            is_human=False,
            role=roles[i],
            personality=personality,
        )

    return GameState(players=players, phase=Phase.NUIT_LOUPS, cycle=1)
