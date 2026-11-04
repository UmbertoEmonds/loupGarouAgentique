from __future__ import annotations

import random

from engine.actions import ActionInvalid, validate_action
from engine.fallback import pick_wolf_tiebreak
from engine.models import ActionType, GameState, Player, Role
from engine.provider import ActionProvider

MAX_WOLF_ROUNDS = 3


def _wolf_context(state: GameState, player: Player) -> dict:
    return {
        "phase": state.phase.value,
        "self_role": player.role.value,
        "known_wolf_ids": [w.id for w in state.wolves() if w.alive and w.id != player.id],
        "alive_players": [
            {"id": p.id, "pseudo": p.pseudo} for p in state.players.values() if p.alive
        ],
        "main_room_log": state.main_room_log,
        "wolf_room_log": state.wolf_room_log,
        "legal_action_types": ["night_kill_target"],
    }


def resolve_wolf_phase(
    state: GameState,
    provider: ActionProvider,
    rng: random.Random | None = None,
) -> str:
    """Mène la négociation des loups sur jusqu'à 3 tours et retourne la cible de la nuit.

    À chaque tour, chaque loup a droit à un seul appel (sans relance) à
    provider.get_action. Un loup dont la réponse est absente, dont
    l'action.type annoncé ne correspond pas à night_kill_target, ou dont
    la cible proposée est invalide ne contribue simplement aucune
    proposition valide ce tour-ci. Si les deux loups ont une proposition
    valide le même tour et qu'ils sont d'accord, cette cible est retournée
    immédiatement. Après MAX_WOLF_ROUNDS tours sans accord,
    pick_wolf_tiebreak tranche en utilisant uniquement la DERNIÈRE
    proposition valide de chaque loup (selon le §2a du design : "le moteur
    tire au sort entre les deux dernières cibles proposées") -- pas toutes
    les propositions distinctes faites sur l'ensemble des tours -- avec un
    repli sur le groupe des non-loups vivants si personne n'a jamais rien
    proposé.
    """
    # Les loups se concertent en privé dans leur salon dédié : chaque tour,
    # chacun propose une victime jusqu'à ce qu'ils se mettent d'accord.
    if rng is None:
        rng = random.Random()

    wolves = [w for w in state.wolves() if w.alive]
    wolf_ids = {w.id for w in state.wolves()}
    alive_non_wolf_ids = [p.id for p in state.players.values() if p.alive and p.id not in wolf_ids]

    last_valid_proposal: dict[str, str] = {}

    for _round in range(MAX_WOLF_ROUNDS):
        round_proposals: dict[str, str] = {}

        for wolf in wolves:
            context = _wolf_context(state, wolf)
            response = provider.get_action(wolf.id, context)
            if response is None:
                continue

            message = response.get("message")
            if message:
                state.wolf_room_log.append({"author": wolf.id, "text": message})

            action_payload = response.get("action") or {}
            if action_payload.get("type") != ActionType.NIGHT_KILL_TARGET.value:
                continue
            target = action_payload.get("target")

            try:
                validated = validate_action(state, wolf.id, ActionType.NIGHT_KILL_TARGET, target)
            except ActionInvalid:
                continue

            round_proposals[wolf.id] = validated.target
            last_valid_proposal[wolf.id] = validated.target

        if len(round_proposals) == len(wolves) and len(set(round_proposals.values())) == 1:
            return next(iter(round_proposals.values()))

    return pick_wolf_tiebreak(list(last_valid_proposal.values()), alive_non_wolf_ids, rng)


def _witch_context(
    state: GameState,
    witch: Player,
    wolf_target: str,
    legal_action_types: list[str],
) -> dict:
    return {
        "phase": state.phase.value,
        "self_role": witch.role.value,
        "known_wolf_ids": [],
        "alive_players": [
            {"id": p.id, "pseudo": p.pseudo} for p in state.players.values() if p.alive
        ],
        "main_room_log": state.main_room_log,
        "wolf_room_log": None,
        "legal_action_types": legal_action_types,
        "wolf_target_tonight": wolf_target,
    }


def resolve_witch_phase(
    state: GameState,
    provider: ActionProvider,
    wolf_target: str,
) -> tuple[bool, str | None]:
    """Mène le sous-appel de soin et le sous-appel de poison de la sorcière.

    Chaque potion donne droit à au plus un appel (sans relance) à
    provider.get_action, et seulement si cette potion n'a pas déjà été
    utilisée lors d'un cycle précédent. Une réponse absente ou une
    proposition invalide (y compris un auto-soin) est traitée comme un
    refus d'utiliser cette potion. Retourne (healed, poisoned_id).
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
    poisoned_id: str | None = None

    if not witch.witch_heal_used:
        response = provider.get_action(witch.id, _witch_context(state, witch, wolf_target, ["witch_heal"]))
        if response is not None:
            action_payload = response.get("action") or {}
            validated = None
            if action_payload.get("type") == ActionType.WITCH_HEAL.value:
                target = action_payload.get("target")
                try:
                    validated = validate_action(state, witch.id, ActionType.WITCH_HEAL, target)
                except ActionInvalid:
                    validated = None
            if validated is not None and validated.target is not None:
                witch.witch_heal_used = True
                healed = True

    if not witch.witch_poison_used:
        response = provider.get_action(witch.id, _witch_context(state, witch, wolf_target, ["witch_poison"]))
        if response is not None:
            action_payload = response.get("action") or {}
            validated = None
            if action_payload.get("type") == ActionType.WITCH_POISON.value:
                target = action_payload.get("target")
                try:
                    validated = validate_action(state, witch.id, ActionType.WITCH_POISON, target)
                except ActionInvalid:
                    validated = None
            if validated is not None and validated.target is not None:
                witch.witch_poison_used = True
                poisoned_id = validated.target

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
