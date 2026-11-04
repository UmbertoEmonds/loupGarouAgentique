"""Les deux seuls recours au hasard autorisés dans le moteur.

Le hasard n'est jamais une règle du jeu. Il n'est utilisé ici que comme
filet de sécurité technique : débloquer une négociation de loups dans
l'impasse, et choisir une cible de vote obligatoire quand un agent ne
répond pas. La résolution de nuit/jour doit appeler ces fonctions et ne
doit jamais implémenter sa propre logique aléatoire.
"""

from __future__ import annotations

import random


def pick_wolf_tiebreak(
    candidate_targets: list[str],
    alive_non_wolf_ids: list[str],
    rng: random.Random,
) -> str:
    """Débloque une impasse entre loups : choisit parmi les cibles proposées, sinon n'importe quel non-loup vivant."""
    proposed = list(dict.fromkeys(candidate_targets))
    if proposed:
        return rng.choice(proposed)
    return rng.choice(alive_non_wolf_ids)


def pick_vote_fallback(
    votes_so_far: dict[str, str],
    alive_ids: list[str],
    rng: random.Random,
) -> str:
    """Choisit une cible de vote obligatoire : préfère un joueur vivant déjà soupçonné, sinon n'importe quel joueur vivant."""
    alive = set(alive_ids)
    suspected = [target for target in dict.fromkeys(votes_so_far.values()) if target in alive]
    if suspected:
        return rng.choice(suspected)
    return rng.choice(alive_ids)
