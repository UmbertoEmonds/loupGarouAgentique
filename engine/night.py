from __future__ import annotations

import random

from engine.actions import validated_target
from engine.context import build_context
from engine.fallback import pick_wolf_tiebreak
from engine.models import ActionType, GameState, Player, Role
from engine.provider import ActionProvider

MAX_WOLF_ROUNDS = 3


def _first_night(state: GameState) -> bool:
    """Avant le premier jour, personne ne sait rien de personne.

    Ce soir-là, le moteur ne consulte pas les IA : un modèle interrogé sans
    aucune information inventait des faits pour justifier son choix
    (« Sarah a trop parlé »). Un tirage au sort donne le même résultat, sans
    invention et sans consommer d'appels. L'humain, lui, est toujours consulté.
    """
    return state.cycle == 1


def _blind_ally_response(
    state: GameState,
    wolf: Player,
    human_wolves: list[Player],
    round_proposals: dict[str, str],
    last_proposal: dict[str, str],
    alive_non_wolf_ids: list[str],
    rng: random.Random,
) -> dict:
    """Réponse d'un loup IA la première nuit, aux côtés d'un loup humain.

    Il se rallie à la dernière proposition de l'humain ; sans proposition, il
    en fait une au hasard en le disant, une seule fois, puis s'y tient.
    """
    human_target = next(
        (round_proposals.get(h.id) or last_proposal.get(h.id)
         for h in human_wolves if round_proposals.get(h.id) or last_proposal.get(h.id)),
        None,
    )
    own = last_proposal.get(wolf.id)
    if human_target is not None:
        message = None if human_target == own else f"D'accord pour {state.players[human_target].pseudo}."
        target = human_target
    elif own is not None:
        message, target = None, own
    else:
        target = rng.choice(alive_non_wolf_ids)
        message = (
            f"Première nuit, on ne sait rien de personne : je propose "
            f"{state.players[target].pseudo}, au hasard."
        )
    return {"message": message, "action": {"type": ActionType.NIGHT_KILL_TARGET.value, "target": target}}


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
    # Sépare les nuits dans l'antre : sans repère, un loup confondait les
    # propositions de la nuit précédente avec celles de la nuit en cours.
    state.wolf_room_log.append({"author": None, "text": f"🌙 Nuit {state.cycle}"})

    human_wolves = [w for w in wolves if w.is_human]
    blind = _first_night(state)
    if blind and not human_wolves:
        # Deux loups IA et aucune information : pas de concertation à mener.
        target = rng.choice(alive_non_wolf_ids)
        state.wolf_room_log.append({
            "author": None,
            "text": f"Première nuit, personne ne sait rien : le sort désigne "
                    f"{state.players[target].pseudo}.",
        })
        return target

    for round_number in range(1, MAX_WOLF_ROUNDS + 1):
        round_proposals: dict[str, str] = {}
        state.wolf_room_log.append({
            "author": None,
            "text": f"Tour de concertation {round_number}/{MAX_WOLF_ROUNDS}.",
        })

        for wolf in wolves:
            if blind and not wolf.is_human:
                response = _blind_ally_response(
                    state, wolf, human_wolves, round_proposals, last_proposal, alive_non_wolf_ids, rng
                )
            else:
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
                # La cible choisie est annoncée aux loups : sinon seul le
                # texte du message est visible et un loup ne peut pas savoir
                # ce que son allié a réellement désigné.
                state.wolf_room_log.append({
                    "author": None,
                    "text": f"{wolf.pseudo} propose {state.players[target].pseudo}.",
                })
                round_proposals[wolf.id] = target
                last_proposal[wolf.id] = target

        everyone_proposed = len(round_proposals) == len(wolves)
        all_agree = len(set(round_proposals.values())) == 1
        if everyone_proposed and all_agree:
            return next(iter(round_proposals.values()))

    target = pick_wolf_tiebreak(list(last_proposal.values()), alive_non_wolf_ids, rng)
    state.wolf_room_log.append({
        "author": None,
        "text": f"Pas d'accord après {MAX_WOLF_ROUNDS} tours : le sort désigne "
                f"{state.players[target].pseudo}.",
    })
    return target


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
    # La première nuit, une sorcière IA n'a aucun suspect : son poison serait
    # tiré à l'aveugle, on ne le lui propose donc pas. Le soin reste une vraie
    # décision (elle sait qui est visé), et l'humaine garde tous ses choix.
    blind_ai_witch = _first_night(state) and not witch.is_human
    if not witch.witch_poison_used and not blind_ai_witch:
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
