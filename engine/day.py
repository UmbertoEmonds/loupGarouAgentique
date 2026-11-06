from __future__ import annotations

import random
from collections import Counter
from typing import Callable

from engine.actions import validated_target
from engine.context import build_context
from engine.fallback import pick_vote_fallback
from engine.models import ActionType, GameState
from engine.provider import ActionProvider, request_with_retry


def run_debate_round_robin(
    state: GameState,
    provider: ActionProvider,
    is_time_up: Callable[[], bool],
) -> None:
    """Mène le débat public : un tour à essai unique par joueur vivant, à la ronde.

    Avant chaque tour de joueur, vérifie is_time_up() et retourne
    immédiatement si c'est le cas. Chaque tour est un seul appel (sans
    relance) à provider.get_action ; une réponse absente ou sans message
    "passe" ce tour-là. Un message non vide est ajouté à main_room_log et
    remet à zéro le compteur de passes consécutives ; une passe
    l'incrémente. Une fois que le compteur atteint un tour complet où tous
    les joueurs vivants passent, le débat s'arrête en avance.
    """
    # Le village débat à voix haute dans le salon principal, à tour de
    # rôle, jusqu'à ce que le temps soit écoulé ou que tout le monde passe.
    alive_ids = state.alive_ids()
    if not alive_ids:
        return

    pass_streak = 0
    while True:
        for player_id in alive_ids:
            if is_time_up():
                return

            player = state.get(player_id)
            context = build_context(state, player, [])
            response = provider.get_action(player_id, context)
            message = response.get("message") if response is not None else None

            if message:
                state.main_room_log.append({"author": player_id, "text": message})
                pass_streak = 0
            else:
                pass_streak += 1
                if pass_streak >= len(alive_ids):
                    return


def collect_votes(
    state: GameState,
    provider: ActionProvider,
    rng: random.Random | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Recueille un vote obligatoire auprès de chaque joueur vivant.

    Chaque joueur a droit à une relance (attempts=2) puisque le vote est
    obligatoire. Faute de vote valide, pick_vote_fallback en attribue un
    d'office et le votant est enregistré dans fallback_used : le vote
    reste obligatoire dans tous les cas.
    """
    # Chaque joueur encore en vie vote publiquement pour éliminer un
    # autre joueur ; le vote est obligatoire, jamais contre soi-même.
    if rng is None:
        rng = random.Random()

    alive_ids = state.alive_ids()
    votes: dict[str, str] = {}
    fallback_used: list[str] = []

    for player_id in alive_ids:
        player = state.get(player_id)
        context = build_context(state, player, [ActionType.DAY_VOTE.value])
        response = request_with_retry(provider, player_id, context, attempts=2)

        target = validated_target(state, player_id, response, ActionType.DAY_VOTE)
        if target is None:
            # Pas de vote exploitable : le moteur en attribue un d'office,
            # de préférence sur un joueur déjà soupçonné ce tour-ci.
            target = pick_vote_fallback(votes, alive_ids, rng, voter_id=player_id)
            fallback_used.append(player_id)

        votes[player_id] = target

    return votes, fallback_used


def resolve_vote(votes: dict[str, str]) -> str | None:
    """Dépouille le vote du jour : le joueur avec le plus de voix, sans égalité, est éliminé.

    Une égalité sur le meilleur score, quelle que soit sa taille (deux,
    trois joueurs ou plus), n'élimine personne.
    """
    # Dépouillement : le village écarte le joueur le plus voté, à moins
    # qu'il n'y ait égalité, auquel cas personne n'est éliminé ce jour-là.
    tally = Counter(votes.values())
    if not tally:
        return None

    top_count = max(tally.values())
    leaders = [candidate for candidate, count in tally.items() if count == top_count]

    if len(leaders) == 1:
        return leaders[0]
    return None
