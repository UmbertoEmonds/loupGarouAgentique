from __future__ import annotations

from dataclasses import dataclass

from engine.models import ActionType, GameState, Role


class ActionInvalid(Exception):
    """Levée quand l'action proposée par un agent enfreint une règle du jeu."""


@dataclass(frozen=True)
class Action:
    type: ActionType
    target: str | None


ROLE_FOR_ACTION: dict[ActionType, Role] = {
    ActionType.NIGHT_KILL_TARGET: Role.LOUP,
    ActionType.WITCH_HEAL: Role.SORCIERE,
    ActionType.WITCH_POISON: Role.SORCIERE,
}

# Seules ces actions peuvent être soumises sans cible, pour la décliner.
DECLINABLE_ACTIONS = {ActionType.WITCH_HEAL, ActionType.WITCH_POISON}


def validate_action(
    state: GameState,
    player_id: str,
    action_type: ActionType,
    target: str | None,
) -> Action:
    """Vérifie l'action proposée par un agent par rapport aux règles du jeu.

    Retourne l'Action validée, ou lève ActionInvalid. Le moteur ne fait
    jamais confiance à la proposition elle-même : chaque vérification
    ci-dessous s'applique quoi que l'agent prétende.
    """
    actor = state.players.get(player_id)
    if actor is None:
        raise ActionInvalid(f"unknown player {player_id!r}")
    if not actor.alive:
        raise ActionInvalid(f"dead player {player_id!r} cannot act")

    if action_type == ActionType.DAY_VOTE:
        pass  # any role may vote
    elif ROLE_FOR_ACTION.get(action_type) != actor.role:
        raise ActionInvalid(f"{action_type.value} is not allowed for role {actor.role.value}")

    if target is None:
        if action_type not in DECLINABLE_ACTIONS:
            raise ActionInvalid(f"{action_type.value} requires a target")
        return Action(action_type, None)

    victim = state.players.get(target)
    if victim is None:
        raise ActionInvalid(f"unknown target {target!r}")
    if not victim.alive:
        raise ActionInvalid(f"target {target!r} is dead")

    if action_type in (ActionType.DAY_VOTE, ActionType.WITCH_POISON) and target == player_id:
        raise ActionInvalid(f"{action_type.value} cannot target oneself")
    if action_type == ActionType.NIGHT_KILL_TARGET and victim.role == Role.LOUP:
        raise ActionInvalid("wolves cannot target other wolves")
    if action_type == ActionType.WITCH_HEAL:
        if target != state.last_wolf_target:
            raise ActionInvalid("witch can only heal the wolves' victim")
        if target == player_id:
            raise ActionInvalid("witch cannot heal herself")

    return Action(action_type, target)


def validated_target(
    state: GameState,
    player_id: str,
    response: dict | None,
    action_type: ActionType,
) -> str | None:
    """Extrait d'une réponse d'agent la cible validée pour l'action attendue.

    C'est l'application concrète du principe "l'IA propose, le moteur
    valide", et le seul chemin par lequel une proposition d'agent devient
    une action jouable. Donnent toutes None, c'est-à-dire "aucune action
    valide" :
    - une réponse absente (agent en échec ou hors délai) ;
    - une action d'un autre type que celui demandé par la phase en cours
      (l'agent ne choisit pas ce qu'on lui demande) ;
    - une cible qui enfreint une règle (joueur mort, loup visant un loup,
      sorcière se soignant elle-même...) ;
    - une potion volontairement déclinée, qui revient au même pour
      l'appelant : aucune potion n'est consommée.
    """
    if response is None:
        return None

    action = response.get("action") or {}
    if action.get("type") != action_type.value:
        return None

    try:
        return validate_action(state, player_id, action_type, action.get("target")).target
    except ActionInvalid:
        return None
