"""The only two sanctioned randomness fallbacks in the engine.

Randomness is never a game rule. It is used here strictly as a technical
safety net: breaking a wolf-negotiation deadlock, and picking a mandatory
vote target when an agent fails to respond. Night/day resolution must call
these functions and must not implement their own random logic.
"""

from __future__ import annotations

import random


def pick_wolf_tiebreak(
    candidate_targets: list[str],
    alive_non_wolf_ids: list[str],
    rng: random.Random,
) -> str:
    """Break a wolf deadlock: choose among proposed targets, else any alive non-wolf."""
    proposed = list(dict.fromkeys(candidate_targets))
    if proposed:
        return rng.choice(proposed)
    return rng.choice(alive_non_wolf_ids)


def pick_vote_fallback(
    votes_so_far: dict[str, str],
    alive_ids: list[str],
    rng: random.Random,
) -> str:
    """Pick a mandatory vote target: prefer an already-suspected alive player, else any alive player."""
    alive = set(alive_ids)
    suspected = [target for target in dict.fromkeys(votes_so_far.values()) if target in alive]
    if suspected:
        return rng.choice(suspected)
    return rng.choice(alive_ids)
