from __future__ import annotations

import random

from engine.actions import validated_target
from engine.context import build_context
from engine.fallback import pick_wolf_tiebreak
from engine.models import ActionType, GameState, Player, Role
from engine.provider import ActionProvider

MAX_WOLF_ROUNDS = 3


def resolve_wolf_phase(
    state: GameState,
    provider: ActionProvider,
    rng: random.Random | None = None,
) -> str:
    """Mène la négociation des loups sur jusqu'à 3 tours et retourne la cible de la nuit.

    À chaque tour, chaque loup a droit à un seul appel (sans relance) à
    provider.get_action. Un loup sans proposition valide ce tour-ci (pas
    de réponse, mauvais type d'action, ou cible illégale) ne compte tout
    simplement pas. Dès que tous les loups vivants proposent la même
    cible le même tour, elle est retournée immédiatement. Après
    MAX_WOLF_ROUNDS tours sans accord, pick_wolf_tiebreak tranche entre
    la DERNIÈRE proposition de chaque loup (§2a du design : "le moteur
    tire au sort entre les deux dernières cibles proposées"), ou parmi
    les non-loups vivants si personne n'a jamais rien proposé.
    """
    # Les loups se concertent en privé dans leur salon dédié : chaque tour,
    # chacun propose une victime jusqu'à ce qu'ils se mettent d'accord.
    if rng is None:
        rng = random.Random()

    wolves = [w for w in state.wolves() if w.alive]
    alive_non_wolf_ids = [
        p.id for p in state.players.values() if p.alive and p.role != Role.LOUP
    ]

    last_proposal: dict[str, str] = {}

    for _round in range(MAX_WOLF_ROUNDS):
        round_proposals: dict[str, str] = {}

        for wolf in wolves:
            context = build_context(state, wolf, [ActionType.NIGHT_KILL_TARGET.value])
            response = provider.get_action(wolf.id, context)

            # Ce que le loup dit est publié dans le salon des loups même si
            # l'action qui l'accompagne est refusée : c'est de la parole,
            # pas un coup joué.
            message = (response or {}).get("message")
            if message:
                state.wolf_room_log.append({"author": wolf.id, "text": message})

            target = validated_target(state, wolf.id, response, ActionType.NIGHT_KILL_TARGET)
            if target is not None:
                round_proposals[wolf.id] = target
                last_proposal[wolf.id] = target

        everyone_proposed = len(round_proposals) == len(wolves)
        all_agree = len(set(round_proposals.values())) == 1
        if everyone_proposed and all_agree:
            return next(iter(round_proposals.values()))

    return pick_wolf_tiebreak(list(last_proposal.values()), alive_non_wolf_ids, rng)


def _ask_witch(
    state: GameState,
    provider: ActionProvider,
    witch: Player,
    wolf_target: str,
    action_type: ActionType,
) -> str | None:
    """Demande à la sorcière si elle utilise une potion ; retourne la cible validée, ou None."""
    context = build_context(
        state, witch, [action_type.value], wolf_target_tonight=wolf_target
    )
    response = provider.get_action(witch.id, context)
    return validated_target(state, witch.id, response, action_type)


def resolve_witch_phase(
    state: GameState,
    provider: ActionProvider,
    wolf_target: str,
) -> tuple[bool, str | None]:
    """Mène le sous-appel de soin et le sous-appel de poison de la sorcière.

    Chaque potion donne droit à au plus un appel (sans relance), et
    seulement si elle n'a pas déjà été utilisée lors d'un cycle
    précédent. Pas de réponse, réponse invalide ou refus explicite
    reviennent au même : la potion n'est pas consommée.
    Retourne (healed, poisoned_id).
    """
    # La sorcière découvre qui les loups ont désigné cette nuit, puis
    # décide, indépendamment, d'utiliser sa potion de soin et/ou de poison.
    witch = next(
        (p for p in state.players.values() if p.role == Role.SORCIERE and p.alive),
        None,
    )
    if witch is None:
        return (False, None)

    # La vérification de validité du soin dans validate_action compare à
    # state.last_wolf_target, qui doit donc refléter le choix des loups
    # de ce soir.
    state.last_wolf_target = wolf_target

    healed = False
    if not witch.witch_heal_used:
        if _ask_witch(state, provider, witch, wolf_target, ActionType.WITCH_HEAL) is not None:
            witch.witch_heal_used = True
            healed = True

    poisoned_id: str | None = None
    if not witch.witch_poison_used:
        poisoned_id = _ask_witch(state, provider, witch, wolf_target, ActionType.WITCH_POISON)
        if poisoned_id is not None:
            witch.witch_poison_used = True

    return (healed, poisoned_id)


def apply_night_deaths(
    state: GameState,
    wolf_target: str,
    healed: bool,
    poisoned_id: str | None,
) -> list[str]:
    """Applique les morts de cette nuit à l'état et retourne qui est mort, sans doublon."""
    # Résolution finale de la nuit : la victime des loups meurt sauf si la
    # sorcière l'a soignée ; sa victime à elle meurt dans tous les cas.
    dead_ids: set[str] = set()
    if not healed:
        dead_ids.add(wolf_target)
    if poisoned_id is not None:
        dead_ids.add(poisoned_id)

    for player_id in dead_ids:
        state.players[player_id].alive = False

    return sorted(dead_ids)
