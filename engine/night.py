from __future__ import annotations

import random

from engine.actions import ActionInvalid, validate_action
from engine.fallback import pick_wolf_tiebreak
from engine.models import ActionType, GameState, Player
from engine.provider import ActionProvider

MAX_WOLF_ROUNDS = 3


def _wolf_context(state: GameState, player: Player) -> dict:
    return {
        "phase": state.phase.value,
        "self_role": player.role.value,
        "known_wolf_ids": [w.id for w in state.wolves() if w.id != player.id],
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
    provider.get_action. A wolf whose response is missing or whose proposed
    target is invalid simply contributes no valid proposal that round. If
    both wolves have a valid proposal in the same round and they agree,
    that target is returned immediately. After MAX_WOLF_ROUNDS rounds
    without agreement, pick_wolf_tiebreak breaks the tie using every
    distinct valid proposal ever made (falling back to the alive non-wolf
    pool if nobody ever proposed anything).
    """
    if rng is None:
        rng = random.Random()

    wolves = state.wolves()
    wolf_ids = {w.id for w in wolves}
    alive_non_wolf_ids = [p.id for p in state.players.values() if p.alive and p.id not in wolf_ids]

    all_valid_proposals: list[str] = []

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
            target = action_payload.get("target")

            try:
                validated = validate_action(state, wolf.id, ActionType.NIGHT_KILL_TARGET, target)
            except ActionInvalid:
                continue

            round_proposals[wolf.id] = validated.target
            all_valid_proposals.append(validated.target)

        if len(round_proposals) == len(wolves) and len(set(round_proposals.values())) == 1:
            return next(iter(round_proposals.values()))

    return pick_wolf_tiebreak(all_valid_proposals, alive_non_wolf_ids, rng)
