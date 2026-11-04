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
    """Run the up-to-3-round wolf negotiation and return the night's kill target.

    Each round, every wolf gets a single (non-retried) call to
    provider.get_action. A wolf whose response is missing, whose claimed
    action.type doesn't match night_kill_target, or whose proposed target
    is invalid simply contributes no valid proposal that round. If both
    wolves have a valid proposal in the same round and they agree, that
    target is returned immediately. After MAX_WOLF_ROUNDS rounds without
    agreement, pick_wolf_tiebreak breaks the tie using only each wolf's
    LAST valid proposal (per spec §2a: "le moteur tire au sort entre les
    deux dernières cibles proposées") -- not every distinct proposal made
    across all rounds -- falling back to the alive non-wolf pool if nobody
    ever proposed anything.
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
    """Run the witch's single heal sub-call and single poison sub-call.

    Each potion gets at most one (non-retried) call to provider.get_action,
    and only if that potion hasn't already been used in a previous cycle.
    A missing response or an invalid proposal (including a self-heal) is
    treated as a decline for that potion. Returns (healed, poisoned_id).
    """
    # La sorcière découvre qui les loups ont désigné cette nuit, puis
    # décide, indépendamment, d'utiliser sa potion de soin et/ou de poison.
    witch = next(
        (p for p in state.players.values() if p.role == Role.SORCIERE and p.alive),
        None,
    )
    if witch is None:
        return (False, None)

    # The heal-validity check in validate_action compares against
    # state.last_wolf_target, so it must reflect tonight's wolf pick.
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
    """Apply this night's deaths to the state and return who died, deduplicated."""
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
