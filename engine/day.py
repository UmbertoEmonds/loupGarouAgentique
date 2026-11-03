from __future__ import annotations

import random
from collections import Counter
from typing import Callable

from engine.actions import ActionInvalid, validate_action
from engine.fallback import pick_vote_fallback
from engine.models import ActionType, GameState, Player, Role
from engine.provider import ActionProvider, request_with_retry


def _day_context(state: GameState, player: Player, legal_action_types: list[str]) -> dict:
    is_wolf = player.role == Role.LOUP
    return {
        "phase": state.phase.value,
        "self_role": player.role.value,
        "known_wolf_ids": [w.id for w in state.wolves() if w.id != player.id] if is_wolf else [],
        "alive_players": [
            {"id": p.id, "pseudo": p.pseudo} for p in state.players.values() if p.alive
        ],
        "main_room_log": state.main_room_log,
        "wolf_room_log": state.wolf_room_log if is_wolf else None,
        "legal_action_types": legal_action_types,
    }


def run_debate_round_robin(
    state: GameState,
    provider: ActionProvider,
    is_time_up: Callable[[], bool],
) -> None:
    """Run the public debate: one single-attempt turn per alive player, round-robin.

    Before each player's turn, check is_time_up() and return immediately if
    so. Each turn is a single (non-retried) call to provider.get_action; a
    missing response or a response with no message "passes" for that turn.
    A non-empty message is appended to main_room_log and resets the
    pass-streak counter; a pass increments it. Once the streak reaches one
    full round of all-alive-players passing, the debate ends early.
    """
    alive_ids = state.alive_ids()
    if not alive_ids:
        return

    pass_streak = 0
    while True:
        for player_id in alive_ids:
            if is_time_up():
                return

            player = state.get(player_id)
            context = _day_context(state, player, [])
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
    """Collect a mandatory vote from every alive player.

    Each player gets request_with_retry(..., attempts=2) since voting is
    mandatory. A successful response is validated via validate_action; a
    None result, or a response that fails validation, is treated as a
    failure to vote and resolved via pick_vote_fallback, recording the
    voter id in fallback_used. The fallback choice is also stored as that
    player's vote, since a vote stays mandatory either way.
    """
    if rng is None:
        rng = random.Random()

    alive_ids = state.alive_ids()
    votes: dict[str, str] = {}
    fallback_used: list[str] = []

    for player_id in alive_ids:
        player = state.get(player_id)
        context = _day_context(state, player, ["day_vote"])
        response = request_with_retry(provider, player_id, context, attempts=2)

        validated_target: str | None = None
        if response is not None:
            target = (response.get("action") or {}).get("target")
            try:
                validated = validate_action(state, player_id, ActionType.DAY_VOTE, target)
                validated_target = validated.target
            except ActionInvalid:
                validated_target = None

        if validated_target is not None:
            votes[player_id] = validated_target
        else:
            fallback_target = pick_vote_fallback(votes, alive_ids, rng)
            fallback_used.append(player_id)
            votes[player_id] = fallback_target

    return votes, fallback_used


def resolve_vote(votes: dict[str, str], alive_ids: list[str]) -> str | None:
    """Resolve the day vote: the player with a uniquely-held top vote count is eliminated.

    A tie for the top count, of any size (two-way, three-way, or more),
    eliminates nobody.
    """
    tally = Counter(votes.values())
    if not tally:
        return None

    top_count = max(tally.values())
    leaders = [candidate for candidate, count in tally.items() if count == top_count]

    if len(leaders) == 1:
        return leaders[0]
    return None
